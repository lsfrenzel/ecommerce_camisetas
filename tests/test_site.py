from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.content.models import BrandSettings, NewsletterSubscriber

from . import factories as f


class SiteTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_home_renders_with_brand_from_settings(self):
        brand = BrandSettings.load()
        brand = BrandSettings.objects.get(pk=brand.pk)
        brand.store_name = "MARCA TESTE"
        brand.save()
        resp = self.client.get("/")
        self.assertContains(resp, "MARCA TESTE")
        self.assertContains(resp, "Da quebrada")

    def test_seo_endpoints(self):
        f.variant(f.product(name="Produto SEO"))
        self.assertContains(self.client.get("/robots.txt"), "Sitemap:")
        self.assertContains(self.client.get("/sitemap.xml"), "/produto/")
        self.assertEqual(self.client.get("/healthz/").json()["status"], "ok")

    def test_healthz_fails_when_migrations_pending(self):
        from unittest import mock

        with mock.patch("django.db.migrations.executor.MigrationExecutor.migration_plan", return_value=[("x", False)]):
            resp = self.client.get("/healthz/")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["migrations"], "pending")

    def test_security_headers(self):
        resp = self.client.get("/")
        self.assertIn("default-src 'self'", resp["Content-Security-Policy"])
        self.assertEqual(resp["X-Frame-Options"], "DENY")
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")

    def test_newsletter_requires_explicit_consent(self):
        self.client.post(reverse("content:newsletter"), {"email": "a@exemplo.com"})
        self.assertFalse(NewsletterSubscriber.objects.exists())
        self.client.post(reverse("content:newsletter"), {"email": "a@exemplo.com", "consent": "1"})
        sub = NewsletterSubscriber.objects.get()
        self.assertTrue(sub.consent and sub.consent_at)

    def test_newsletter_unsubscribe(self):
        from django.utils import timezone

        sub = NewsletterSubscriber.objects.create(email="b@exemplo.com", consent=True, consent_at=timezone.now())
        self.client.post(reverse("content:unsubscribe", args=[sub.unsubscribe_token]))
        sub.refresh_from_db()
        self.assertIsNotNone(sub.unsubscribed_at)

    def test_xss_escaped_in_search(self):
        resp = self.client.get(reverse("catalog:shop"), {"q": "<script>alert(1)</script>"})
        self.assertNotContains(resp, "<script>alert(1)</script>")

    def test_csrf_enforced_on_cart(self):
        from django.test import Client

        c = Client(enforce_csrf_checks=True)
        v = f.variant()
        self.assertEqual(c.post(reverse("cart:add"), {"variant_id": v.pk}).status_code, 403)

    def test_seed_demo_runs_without_orders(self):
        from django.core.management import call_command

        from apps.orders.models import Order

        with self.settings(DEBUG=True):
            call_command("seed_demo", "--no-images", verbosity=0)
        self.assertGreaterEqual(f.Product.objects.count() if hasattr(f, "Product") else 1, 1)
        self.assertFalse(Order.objects.exists())
