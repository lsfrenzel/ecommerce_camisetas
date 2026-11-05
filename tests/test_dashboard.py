from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Product
from apps.core.models import AuditLog
from apps.orders.models import OrderStatus
from apps.orders.services import create_order_from_cart, mark_paid
from apps.promotions.models import Coupon, Promotion

from . import factories as f


class PermissionTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_anonymous_redirected_customer_forbidden(self):
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 302)
        self.client.force_login(f.user())
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 403)
        self.assertEqual(self.client.get(reverse("dashboard:orders")).status_code, 403)

    def test_role_based_access(self):
        stock = f.staff("Estoquista")
        self.client.force_login(stock)
        self.assertEqual(self.client.get(reverse("dashboard:inventory")).status_code, 200)
        self.assertEqual(self.client.get(reverse("dashboard:reports")).status_code, 403)
        self.assertEqual(self.client.get(reverse("dashboard:team")).status_code, 403)
        self.assertEqual(self.client.get(reverse("dashboard:cupons_list")).status_code, 403)
        # Estoquista vê produtos mas não pode alterar preço via POST direto
        p = f.product(price="100.00")
        resp = self.client.post(reverse("dashboard:product_edit", args=[p.pk]), {"name": "hack", "price": "1"})
        self.assertEqual(resp.status_code, 403)
        p.refresh_from_db()
        self.assertEqual(p.price, Decimal("100.00"))

    def test_attendance_cannot_cancel_order(self):
        method = f.shipping_fixed()
        order = create_order_from_cart(f.cart_with(f.variant(stock=3)), f.checkout_data(shipping_code=f"m{method.pk}"))
        self.client.force_login(f.staff("Atendimento"))
        resp = self.client.post(reverse("dashboard:order_cancel", args=[order.number]), {"reason": "x"})
        self.assertEqual(resp.status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.AWAITING_PAYMENT)

    def test_manager_sees_reports_but_not_team(self):
        self.client.force_login(f.staff("Gestor comercial"))
        self.assertEqual(self.client.get(reverse("dashboard:reports")).status_code, 200)
        self.assertEqual(self.client.get(reverse("dashboard:team")).status_code, 403)

    def test_non_superuser_cannot_grant_admin_role(self):
        ensure_admin = f.staff("Administrador geral")
        target = f.staff("Atendimento")
        self.client.force_login(ensure_admin)
        resp = self.client.post(reverse("dashboard:team_role", args=[target.pk]), {"role": "Administrador geral"})
        self.assertEqual(resp.status_code, 403)
        resp = self.client.post(reverse("dashboard:team_role", args=[target.pk]), {"role": "Estoquista"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(target.groups.filter(name="Estoquista").exists())
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.PERMISSION_CHANGE).exists())


class AdminOperationsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = f.staff("Administrador geral")
        self.client.force_login(self.admin)

    def _formset(self, prefix, total=0, initial=0):
        return {f"{prefix}-TOTAL_FORMS": str(total), f"{prefix}-INITIAL_FORMS": str(initial),
                f"{prefix}-MIN_NUM_FORMS": "0", f"{prefix}-MAX_NUM_FORMS": "1000"}

    def test_create_product_with_variants_and_images(self):
        cat, black, size_m = f.category(), f.color(), f.size("M", 2)
        from django.core.files.uploadedfile import SimpleUploadedFile

        data = {"name": "Camiseta Nova", "slug": "", "sku_base": "nova", "category": cat.pk, "status": "active",
                "price": "129.90", "cost_price": "40", "weight_grams": 300, "length_cm": 30, "width_cm": 25, "height_cm": 4,
                **self._formset("variants", 1), "variants-0-color": black.pk, "variants-0-size": size_m.pk,
                "variants-0-fit": "oversized", "variants-0-sku": "NOVA-PRT-M", "variants-0-low_stock_threshold": 3,
                "variants-0-is_active": "on",
                **self._formset("images", 1), "images-0-view": "front", "images-0-position": 0,
                "images-0-image": SimpleUploadedFile("frente.png", f.png_bytes(1200, 1500), content_type="image/png")}
        import tempfile

        with self.settings(MEDIA_ROOT=tempfile.mkdtemp()):
            resp = self.client.post(reverse("dashboard:product_new"), data)
            self.assertEqual(resp.status_code, 302, getattr(resp, "context", None) and resp.context["form"].errors)
            p = Product.objects.get(sku_base="NOVA")
            self.assertEqual(p.variants.get().sku, "NOVA-PRT-M")
            img = p.images.get()
            self.assertTrue(img.image.name.endswith(".webp"))
            self.assertTrue(img.thumbnail.name.endswith(".webp"))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.CREATE, object_id=str(p.pk)).exists())

    def test_generate_variants_with_initial_stock(self):
        p = f.product()
        colors, sizes = [f.color("Preta"), f.color("Branca", "#fff")], [f.size("M", 2), f.size("G", 3)]
        self.client.post(reverse("dashboard:product_generate_variants", args=[p.pk]), {
            "colors": [c.pk for c in colors], "sizes": [s.pk for s in sizes], "fit": "oversized", "initial_stock": 5})
        self.assertEqual(p.variants.count(), 4)
        self.assertEqual(sum(v.stock for v in p.variants.all()), 20)

    def test_bulk_price_change_audited(self):
        p1, p2 = f.product(price="100.00"), f.product(price="50.00")
        self.client.post(reverse("dashboard:bulk_price"), {"products": [p1.pk, p2.pk], "mode": "percent", "value": "10"})
        p1.refresh_from_db()
        p2.refresh_from_db()
        self.assertEqual((p1.price, p2.price), (Decimal("110.00"), Decimal("55.00")))
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.PRICE_CHANGE).count(), 2)

    def test_bulk_price_rejects_invalid(self):
        p = f.product(price="10.00")
        self.client.post(reverse("dashboard:bulk_price"), {"products": [p.pk], "mode": "amount", "value": "-20"})
        p.refresh_from_db()
        self.assertEqual(p.price, Decimal("10.00"))

    def test_create_coupon_and_promotion(self):
        self.client.post(reverse("dashboard:cupons_new"), {"code": "drop10", "kind": "percent", "value": "10",
                                                            "min_order_value": "0", "max_uses_per_customer": "1", "is_active": "on"})
        self.assertTrue(Coupon.objects.filter(code="DROP10").exists())
        resp = self.client.post(reverse("dashboard:cupons_new"), {"code": "ruim", "kind": "percent", "value": "150",
                                                                   "min_order_value": "0"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Coupon.objects.filter(code="RUIM").exists())
        p = f.product()
        self.client.post(reverse("dashboard:promocoes_new"), {"name": "Drop", "kind": "percent", "value": "20",
                                                               "products": [p.pk], "is_active": "on"})
        self.assertTrue(Promotion.objects.filter(name="Drop").exists())

    def test_inventory_movement_via_panel(self):
        v = f.variant(stock=2)
        self.client.post(reverse("dashboard:inventory"), {"variant": v.pk, "kind": "exit", "quantity": 5, "reason": "x"})
        v.refresh_from_db()
        self.assertEqual(v.stock, 2, "saída maior que o estoque é recusada")
        self.client.post(reverse("dashboard:inventory"), {"variant": v.pk, "kind": "entry", "quantity": 5, "reason": "NF"})
        v.refresh_from_db()
        self.assertEqual(v.stock, 7)

    def test_order_status_flow_and_shipment(self):
        method = f.shipping_fixed()
        order = create_order_from_cart(f.cart_with(f.variant(stock=3)), f.checkout_data(shipping_code=f"m{method.pk}"))
        mark_paid(order)
        for status in ("in_production", "ready_to_ship", "shipped"):
            self.client.post(reverse("dashboard:order_status", args=[order.number]), {"status": status, "notify": "on"})
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.SHIPPED)
        self.client.post(reverse("dashboard:order_shipment", args=[order.number]), {
            "carrier": "Correios", "tracking_code": "BR123456789BR", "status": "in_transit"})
        self.assertEqual(order.shipment.tracking_code, "BR123456789BR")
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.ORDER_STATUS).exists())

    def test_reports_and_csv(self):
        method = f.shipping_fixed(price="10.00")
        order = create_order_from_cart(f.cart_with(f.variant(f.product(price="100.00", cost="30.00"), stock=3), 2),
                                       f.checkout_data(shipping_code=f"m{method.pk}"))
        mark_paid(order)
        resp = self.client.get(reverse("dashboard:reports"), {"periodo": "7d"})
        kpi = resp.context["kpi"]
        self.assertEqual(kpi["revenue"], Decimal("210.00"))
        self.assertEqual(kpi["product_revenue"], Decimal("200.00"))
        self.assertEqual(kpi["cogs"], Decimal("60.00"))
        self.assertEqual(kpi["gross_profit"], Decimal("140.00"))
        csv_resp = self.client.get(reverse("dashboard:reports"), {"periodo": "7d", "r": "produtos", "csv": "1"})
        self.assertEqual(csv_resp["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Unidades", csv_resp.content.decode("utf-8-sig"))
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 200)

    def test_block_customer(self):
        customer = f.user()
        self.client.post(reverse("dashboard:customer_detail", args=[customer.pk]), {"action": "block", "reason": "fraude"})
        customer.refresh_from_db()
        self.assertFalse(customer.is_active)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.ACCOUNT_BLOCK).exists())

    def test_all_dashboard_pages_render(self):
        f.variant(stock=1)
        for name in ["home", "products", "product_new", "inventory", "inventory_history", "orders", "customers",
                     "personalizations", "reports", "team", "support", "data_requests", "audit", "brand", "bulk_price",
                     "categorias_list", "colecoes_list", "cupons_list", "cupons_new", "promocoes_list", "banners_list",
                     "banners_new", "paginas_list", "faq_list", "entregas_list", "posicoes-estampa_list"]:
            self.assertEqual(self.client.get(reverse(f"dashboard:{name}")).status_code, 200, name)


class CsvSafetyTests(TestCase):
    def test_formula_injection_neutralized(self):
        from apps.dashboard.views import _csv_safe

        self.assertEqual(_csv_safe("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(_csv_safe("-10.50"), "-10.50")
