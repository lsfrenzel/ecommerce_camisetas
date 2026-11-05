import shutil
import tempfile
from decimal import Decimal

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.cart.models import Cart
from apps.content.models import BrandSettings
from apps.core.images import validate_and_process_upload
from apps.orders.services import create_order_from_cart
from apps.personalization.models import PersonalizationRequest, PrintPlacement

from . import factories as f

TMP_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TMP_MEDIA, STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": TMP_MEDIA + "/pub"}},
    "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": TMP_MEDIA + "/priv"}},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class UploadValidationTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)

    def test_accepts_real_png_and_strips_metadata(self):
        up = SimpleUploadedFile("arte.png", f.png_bytes(800, 600), content_type="image/png")
        processed = validate_and_process_upload(up, max_mb=5)
        self.assertEqual((processed.width, processed.height, processed.format), (800, 600, "PNG"))

    def test_rejects_disguised_file(self):
        up = SimpleUploadedFile("arte.png", b"<?php echo 'hack'; ?>" + b"0" * 100, content_type="image/png")
        with self.assertRaises(ValidationError):
            validate_and_process_upload(up, max_mb=5)

    def test_rejects_wrong_extension(self):
        up = SimpleUploadedFile("arte.svg", b"<svg onload=alert(1)></svg>", content_type="image/svg+xml")
        with self.assertRaises(ValidationError):
            validate_and_process_upload(up, max_mb=5)

    def test_rejects_too_large(self):
        up = SimpleUploadedFile("arte.png", f.png_bytes(10, 10), content_type="image/png")
        up.size = 30 * 1024 * 1024
        with self.assertRaises(ValidationError):
            validate_and_process_upload(up, max_mb=10)

    def test_rejects_truncated_image(self):
        data = f.png_bytes(500, 500)[:200]
        with self.assertRaises(ValidationError):
            validate_and_process_upload(SimpleUploadedFile("x.png", data), max_mb=5)


@override_settings(MEDIA_ROOT=TMP_MEDIA, STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": TMP_MEDIA + "/pub"}},
    "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": TMP_MEDIA + "/priv"}},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class PersonalizationFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.product = f.product(price="90.00", is_customizable=True)
        self.variant = f.variant(self.product, stock=10)
        self.placement = PrintPlacement.objects.create(name="Costas", code="costas", side="back", fee=Decimal("35.00"))
        self.method = f.shipping_fixed()

    def submit(self, client=None, **extra):
        client = client or self.client
        data = {"product": self.product.pk, "variant": self.variant.pk, "quantity": 2, "placement": self.placement.pk,
                "custom_text": "", "text_color": "#171717", "instructions": "centralizar", "name": "Ana",
                "email": "ana@exemplo.com", "phone": "", "rights_confirmed": "on",
                "image_upload": SimpleUploadedFile("arte.png", f.png_bytes(900, 900), content_type="image/png")}
        data.update(extra)
        return client.post(reverse("personalization:start"), data)

    def test_submission_requires_review_and_stores_privately(self):
        resp = self.submit()
        p = PersonalizationRequest.objects.get()
        self.assertRedirects(resp, p.get_absolute_url())
        self.assertEqual(p.status, "submitted")
        self.assertTrue(p.low_resolution)  # 900 px < mínimo recomendado
        self.assertEqual(p.fee, Decimal("35.00"))
        self.assertTrue(p.image.name.startswith("personalization/"))
        self.assertTrue(p.image.path.startswith(TMP_MEDIA + "/priv") or "priv" in p.image.path)
        self.assertEqual(self.client.get("/media/" + p.image.name).status_code, 404)
        # Dono (mesma sessão) vê a arte; terceiros não.
        self.assertEqual(self.client.get(reverse("personalization:artwork", args=[p.public_id])).status_code, 200)
        other = self.client_class()
        self.assertEqual(other.get(reverse("personalization:artwork", args=[p.public_id])).status_code, 404)
        self.assertEqual(other.get(p.get_absolute_url()).status_code, 404)

    def test_cannot_buy_before_approval_then_full_flow(self):
        self.submit()
        p = PersonalizationRequest.objects.get()
        self.client.post(reverse("personalization:add_to_cart", args=[p.public_id]))
        self.assertFalse(Cart.objects.filter(items__personalization=p).exists())
        # Equipe aprova
        reviewer = f.staff("Atendimento")
        staff_client = self.client_class()
        staff_client.force_login(reviewer)
        staff_client.post(reverse("dashboard:personalization_detail", args=[p.public_id]),
                          {"action": "approve", "admin_notes": "Arte ok", "fee": "35.00"})
        p.refresh_from_db()
        self.assertEqual(p.status, "approved")
        self.client.post(reverse("personalization:add_to_cart", args=[p.public_id]))
        cart = Cart.objects.get(items__personalization=p)
        order = create_order_from_cart(cart, f.checkout_data(shipping_code=f"m{self.method.pk}"))
        self.assertEqual(order.personalization_total, Decimal("70.00"))
        self.assertEqual(order.total, Decimal("180.00") + Decimal("70.00") + order.shipping_cost)
        p.refresh_from_db()
        self.assertEqual(p.status, "ordered")

    def test_without_approval_requirement_goes_to_cart(self):
        brand = BrandSettings.load()
        brand = BrandSettings.objects.get(pk=brand.pk)
        brand.personalization_requires_approval = False
        brand.save()
        resp = self.submit()
        self.assertRedirects(resp, reverse("cart:detail"))
        self.assertEqual(PersonalizationRequest.objects.get().status, "in_cart")

    def test_rejects_malicious_upload_in_form(self):
        resp = self.submit(image_upload=SimpleUploadedFile("arte.png", b"GIF89a<script>", content_type="image/png"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(PersonalizationRequest.objects.exists())

    def test_rights_confirmation_required(self):
        data = {"rights_confirmed": ""}
        resp = self.submit(**data)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(PersonalizationRequest.objects.exists())

    def test_customer_cannot_review(self):
        self.submit()
        p = PersonalizationRequest.objects.get()
        c = self.client_class()
        c.force_login(f.user())
        resp = c.post(reverse("dashboard:personalization_detail", args=[p.public_id]), {"action": "approve"})
        self.assertEqual(resp.status_code, 403)
