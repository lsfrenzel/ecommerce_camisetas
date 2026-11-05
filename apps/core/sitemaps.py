from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class StaticSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        return ["core:home", "catalog:shop", "catalog:collections", "personalization:start", "content:about",
                "content:faq"]

    def location(self, item):
        return reverse(item)


class ProductSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.9

    def items(self):
        from apps.catalog.models import Product

        return Product.objects.visible().order_by("-updated_at")

    def lastmod(self, obj):
        return obj.updated_at


class CollectionSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.7

    def items(self):
        from apps.catalog.models import Collection

        return Collection.objects.filter(is_active=True)

    def lastmod(self, obj):
        return obj.updated_at


class CategorySitemap(CollectionSitemap):
    def items(self):
        from apps.catalog.models import Category

        return Category.objects.filter(is_active=True)


class PageSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.3

    def items(self):
        from apps.content.models import Page

        return Page.objects.filter(is_published=True)

    def lastmod(self, obj):
        return obj.updated_at


SITEMAPS = {
    "static": StaticSitemap,
    "products": ProductSitemap,
    "collections": CollectionSitemap,
    "categories": CategorySitemap,
    "pages": PageSitemap,
}
