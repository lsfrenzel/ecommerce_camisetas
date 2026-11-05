from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Product, ProductVariant
from apps.catalog.pricing import PricingEngine
from apps.promotions.models import Promotion

from . import factories as f


class ProductAndVariantTests(TestCase):
    def test_variant_unique_combination(self):
        v = f.variant()
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductVariant.objects.create(product=v.product, sku="OUTRO", color=v.color, size=v.size, fit=v.fit)

    def test_sizes_have_own_sku_and_stock(self):
        p = f.product()
        m = f.variant(p, stock=5, sz=f.size("M", 2))
        g = f.variant(p, stock=0, sz=f.size("G", 3))
        self.assertNotEqual(m.sku, g.sku)
        self.assertEqual(m.available, 5)
        self.assertEqual(g.available, 0)

    def test_draft_product_is_hidden(self):
        p = f.product(status=Product.Status.DRAFT)
        self.assertEqual(self.client.get(reverse("catalog:product", args=[p.slug])).status_code, 404)

    def test_product_page_renders_with_structured_data(self):
        p = f.product(name="Camiseta Pense Como Jesus")
        f.variant(p)
        resp = self.client.get(p.get_absolute_url())
        self.assertContains(resp, "Camiseta Pense Como Jesus")
        self.assertContains(resp, '"@type": "Product"')

    def test_filters_size_color_availability_and_search(self):
        black, white = f.color("Preta"), f.color("Branca", "#ffffff")
        p1 = f.product(name="Oversized Preta")
        f.variant(p1, stock=3, col=black, sz=f.size("M", 2))
        p2 = f.product(name="Oversized Branca")
        f.variant(p2, stock=0, col=white, sz=f.size("G", 3))
        url = reverse("catalog:shop")
        names = lambda r: [p.name for p in r.context["products"]]  # noqa: E731
        self.assertEqual(names(self.client.get(url, {"cor": "preta"})), ["Oversized Preta"])
        self.assertEqual(names(self.client.get(url, {"tamanho": "G"})), ["Oversized Branca"])
        self.assertEqual(names(self.client.get(url, {"disponivel": "1"})), ["Oversized Preta"])
        self.assertEqual(names(self.client.get(url, {"q": "branca"})), ["Oversized Branca"])
        self.assertEqual(names(self.client.get(url, {"q": p1.variants.first().sku})), ["Oversized Preta"])

    def test_price_filter_and_sort(self):
        f.variant(f.product(name="Barata", price="50.00"))
        f.variant(f.product(name="Cara", price="200.00"))
        resp = self.client.get(reverse("catalog:shop"), {"ordem": "maior-preco"})
        self.assertEqual([p.name for p in resp.context["products"]][:2], ["Cara", "Barata"])
        resp = self.client.get(reverse("catalog:shop"), {"preco_max": "100"})
        self.assertEqual([p.name for p in resp.context["products"]], ["Barata"])

    def test_empty_results_state(self):
        resp = self.client.get(reverse("catalog:shop"), {"q": "nada-existe"})
        self.assertContains(resp, "Nada por aqui")


class PricingTests(TestCase):
    def test_scheduled_sale_price(self):
        now = timezone.now()
        p = f.product(price="100.00", sale_price=Decimal("80.00"), sale_starts_at=now + timedelta(days=1))
        self.assertEqual(PricingEngine(now).price_for(p).final, Decimal("100.00"))
        self.assertEqual(PricingEngine(now + timedelta(days=2)).price_for(p).final, Decimal("80.00"))

    def test_best_promotion_wins_no_stacking(self):
        p = f.product(price="100.00", sale_price=Decimal("90.00"))
        promo = Promotion.objects.create(name="Drop", kind="percent", value=Decimal("25"))
        promo.products.add(p)
        promo2 = Promotion.objects.create(name="Categoria", kind="fixed", value=Decimal("5"))
        promo2.categories.add(p.category)
        info = PricingEngine().price_for(p)
        self.assertEqual(info.final, Decimal("75.00"))
        self.assertEqual(info.label, "Drop")

    def test_inactive_or_expired_promotion_ignored(self):
        p = f.product(price="100.00")
        Promotion.objects.create(name="Off", kind="percent", value=50, is_active=False, applies_to_all=True)
        Promotion.objects.create(name="Exp", kind="percent", value=50, applies_to_all=True,
                                 ends_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(PricingEngine().price_for(p).final, Decimal("100.00"))

    def test_fixed_promotion_never_negative(self):
        p = f.product(price="10.00")
        Promotion.objects.create(name="Big", kind="fixed", value=50, applies_to_all=True)
        self.assertEqual(PricingEngine().price_for(p).final, Decimal("0.00"))
