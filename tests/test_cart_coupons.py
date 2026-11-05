from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cart.models import Cart
from apps.cart.services import summarize
from apps.catalog.models import Product
from apps.promotions.models import Coupon, CouponRedemption, Promotion
from apps.promotions.services import CouponError, PricedLine, evaluate_coupon

from . import factories as f


class CartTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_add_update_remove(self):
        v = f.variant(stock=5)
        self.client.post(reverse("cart:add"), {"variant_id": v.pk, "quantity": 2})
        cart = Cart.objects.get()
        self.assertEqual(cart.items.get().quantity, 2)
        item = cart.items.get()
        self.client.post(reverse("cart:update", args=[item.pk]), {"quantity": 4})
        self.assertEqual(cart.items.get().quantity, 4)
        self.client.post(reverse("cart:remove", args=[item.pk]))
        self.assertFalse(cart.items.exists())

    def test_cannot_add_more_than_available(self):
        v = f.variant(stock=1)
        self.client.post(reverse("cart:add"), {"variant_id": v.pk, "quantity": 2})
        self.assertFalse(Cart.objects.filter(items__isnull=False).exists())

    def test_cannot_add_inactive_product(self):
        v = f.variant(f.product(status=Product.Status.INACTIVE), stock=5)
        self.client.post(reverse("cart:add"), {"variant_id": v.pk, "quantity": 1})
        self.assertFalse(Cart.objects.filter(items__isnull=False).exists())

    def test_htmx_add_triggers_counter_event(self):
        v = f.variant(stock=5)
        resp = self.client.post(reverse("cart:add"), {"variant_id": v.pk, "quantity": 1}, HTTP_HX_REQUEST="true")
        self.assertIn("cart:updated", resp["HX-Trigger"])

    def test_cart_merges_into_user_on_login(self):
        u = f.user(email="m@exemplo.com")
        v = f.variant(stock=5)
        self.client.post(reverse("cart:add"), {"variant_id": v.pk, "quantity": 1})
        self.client.post(reverse("accounts:login"), {"email": "m@exemplo.com", "password": "Senha-Forte-123"})
        self.assertEqual(Cart.objects.get(user=u).items.get().quantity, 1)
        self.assertEqual(Cart.objects.count(), 1)

    def test_prices_always_recalculated_from_database(self):
        v = f.variant(f.product(price="100.00"), stock=5)
        cart = f.cart_with(v, 1)
        Product.objects.filter(pk=v.product_id).update(price=Decimal("120.00"))
        self.assertEqual(summarize(cart).products_subtotal, Decimal("120.00"))


class CouponTests(TestCase):
    def lines(self, price="100.00", original=None, qty=1, product_id=1, category_id=1):
        return [PricedLine(product_id=product_id, category_id=category_id, unit_price=Decimal(price),
                           original_unit_price=Decimal(original or price), quantity=qty)]

    def test_percent_and_fixed(self):
        c = Coupon.objects.create(code="DEZ", kind="percent", value=10)
        self.assertEqual(evaluate_coupon(c, self.lines()).discount, Decimal("10.00"))
        c2 = Coupon.objects.create(code="VINTE", kind="fixed", value=20)
        self.assertEqual(evaluate_coupon(c2, self.lines()).discount, Decimal("20.00"))
        c3 = Coupon.objects.create(code="MUITO", kind="fixed", value=500)
        self.assertEqual(evaluate_coupon(c3, self.lines()).discount, Decimal("100.00"), "desconto nunca excede a base")

    def test_validity_window_and_inactive(self):
        c = Coupon.objects.create(code="EXP", kind="percent", value=10, ends_at=timezone.now() - timedelta(days=1))
        with self.assertRaises(CouponError):
            evaluate_coupon(c, self.lines())
        c2 = Coupon.objects.create(code="OFF", kind="percent", value=10, is_active=False)
        with self.assertRaises(CouponError):
            evaluate_coupon(c2, self.lines())

    def test_min_order_value(self):
        c = Coupon.objects.create(code="MIN", kind="percent", value=10, min_order_value=200)
        with self.assertRaises(CouponError):
            evaluate_coupon(c, self.lines())

    def test_not_stackable_with_promotions(self):
        c = Coupon.objects.create(code="NS", kind="percent", value=10, stackable_with_promotions=False)
        with self.assertRaises(CouponError):
            evaluate_coupon(c, self.lines(price="80.00", original="100.00"))
        c.stackable_with_promotions = True
        c.save()
        self.assertEqual(evaluate_coupon(c, self.lines(price="80.00", original="100.00")).discount, Decimal("8.00"))

    def test_max_discount_cap(self):
        c = Coupon.objects.create(code="CAP", kind="percent", value=50, max_discount=Decimal("15"))
        self.assertEqual(evaluate_coupon(c, self.lines()).discount, Decimal("15.00"))

    def test_usage_limits(self):
        method = f.shipping_fixed()
        v = f.variant(stock=10)
        c = Coupon.objects.create(code="UMA", kind="percent", value=10, max_uses=1, max_uses_per_customer=1)
        from apps.orders.services import create_order_from_cart

        cart = f.cart_with(v, 1)
        cart.coupon = c
        cart.save()
        create_order_from_cart(cart, f.checkout_data(shipping_code=f"m{method.pk}"))
        self.assertEqual(CouponRedemption.objects.count(), 1)
        with self.assertRaises(CouponError):
            evaluate_coupon(c, self.lines(), email="outro@exemplo.com")

    def test_per_customer_limit(self):
        c = Coupon.objects.create(code="CLI", kind="percent", value=10, max_uses_per_customer=1)
        method = f.shipping_fixed()
        v = f.variant(stock=10)
        from apps.orders.services import create_order_from_cart

        cart = f.cart_with(v, 1)
        cart.coupon = c
        cart.save()
        create_order_from_cart(cart, f.checkout_data(shipping_code=f"m{method.pk}", email="cli@exemplo.com"))
        with self.assertRaises(CouponError):
            evaluate_coupon(c, self.lines(), email="CLI@exemplo.com")
        self.assertEqual(evaluate_coupon(c, self.lines(), email="outra@exemplo.com").discount, Decimal("10.00"))

    def test_restricted_to_category(self):
        cat = f.category("Bonés")
        c = Coupon.objects.create(code="CAT", kind="percent", value=10)
        c.categories.add(cat)
        with self.assertRaises(CouponError):
            evaluate_coupon(c, self.lines(category_id=cat.pk + 999))
        self.assertEqual(evaluate_coupon(c, self.lines(category_id=cat.pk)).discount, Decimal("10.00"))

    def test_invalid_percent_blocked_by_database(self):
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            Coupon.objects.create(code="ERRADO", kind="percent", value=150)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Promotion.objects.create(name="Errada", kind="percent", value=95)

    def test_apply_coupon_view(self):
        cache.clear()
        v = f.variant(stock=5)
        self.client.post(reverse("cart:add"), {"variant_id": v.pk, "quantity": 1})
        Coupon.objects.create(code="BEMVINDO10", kind="percent", value=10)
        self.client.post(reverse("cart:coupon"), {"code": "bemvindo10"})
        self.assertEqual(Cart.objects.get().coupon.code, "BEMVINDO10")
