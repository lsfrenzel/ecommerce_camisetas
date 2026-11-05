from django.conf import settings
from django.core.cache import cache


def _rgb(hex_value: str, fallback: str) -> str:
    try:
        h = hex_value.lstrip("#")
        return f"{int(h[0:2], 16)} {int(h[2:4], 16)} {int(h[4:6], 16)}"
    except (ValueError, IndexError, AttributeError):
        return fallback


def nav_categories():
    from apps.catalog.models import Category

    data = cache.get("nav-categories")
    if data is None:
        data = list(Category.objects.filter(is_active=True, show_in_menu=True, parent__isnull=True)
                    .values("name", "slug")[:8])
        cache.set("nav-categories", data, 300)
    return data


def store(request):
    from apps.cart.services import get_cart
    from apps.content.models import BrandSettings, Page

    brand = BrandSettings.load()
    cart_count = 0
    if not request.path.startswith(("/painel/", "/django-admin/", "/healthz")):
        cart = get_cart(request)
        if cart is not None:
            cart_count = sum(cart.items.values_list("quantity", flat=True))
    footer_pages = cache.get("footer-pages")
    if footer_pages is None:
        footer_pages = list(Page.objects.filter(is_published=True, show_in_footer=True).values("title", "slug"))
        cache.set("footer-pages", footer_pages, 300)
    return {
        "brand": brand,
        "brand_vars": {
            "lime": _rgb(brand.accent_color, "199 255 61"),
            "orange": _rgb(brand.accent_secondary, "255 98 59"),
            "blue": _rgb(brand.accent_tertiary, "53 92 255"),
        },
        "cart_count": cart_count,
        "nav_categories": nav_categories(),
        "footer_pages": footer_pages,
        "site_url": settings.SITE_URL,
        "payments_enabled": bool(settings.MERCADOPAGO_ACCESS_TOKEN),
    }
