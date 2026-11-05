import logging

from django.conf import settings
from django.db import connection
from django.db.models import Prefetch
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


def home(request):
    from apps.catalog.models import Collection, Product, ProductImage
    from apps.catalog.pricing import PricingEngine
    from apps.catalog.views import _base_queryset
    from apps.content.models import Banner

    engine = PricingEngine()
    hero = Banner.live(Banner.Placement.HERO).first()
    personalize_banner = Banner.live(Banner.Placement.PERSONALIZE).first()
    strip = Banner.live(Banner.Placement.STRIP).first()

    drop = Collection.objects.filter(is_active=True, is_featured=True).order_by("position", "-release_date").first()
    drop_products = []
    if drop:
        drop_products = list(_base_queryset().filter(collections=drop).order_by("-is_featured", "-created_at")[:6])
        engine.annotate(drop_products)

    featured = list(_base_queryset().filter(is_featured=True).order_by("-created_at")[:4])
    engine.annotate(featured)
    hero_product = (drop_products or featured or [None])[0]

    # Mais vendidos com base em vendas reais (sold_count é atualizado quando pagamentos são aprovados).
    bestsellers = list(_base_queryset().filter(sold_count__gt=0).order_by("-sold_count")[:8])
    bestsellers_are_real = bool(bestsellers)
    if not bestsellers:
        bestsellers = list(_base_queryset().order_by("-created_at")[:8])
    engine.annotate(bestsellers)

    collections = Collection.objects.filter(is_active=True).prefetch_related(
        Prefetch("products", queryset=Product.objects.visible().prefetch_related(
            Prefetch("images", queryset=ProductImage.objects.order_by("position")))
        )
    )[:4]

    return render(request, "home.html", {
        "hero": hero,
        "hero_product": hero_product,
        "strip": strip,
        "personalize_banner": personalize_banner,
        "drop": drop,
        "drop_products": drop_products,
        "featured": featured,
        "bestsellers": bestsellers,
        "bestsellers_are_real": bestsellers_are_real,
        "home_collections": collections,
    })


@require_GET
def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "ok"})
    except Exception:  # noqa: BLE001
        logger.exception("Health check: banco indisponível")
        return JsonResponse({"status": "error", "database": "unavailable"}, status=503)


@require_GET
@cache_control(max_age=3600)
def robots_txt(request):
    lines = [
        "User-agent: *",
        "Disallow: /painel/",
        "Disallow: /django-admin/",
        "Disallow: /conta/",
        "Disallow: /carrinho/",
        "Disallow: /pedidos/",
        "Disallow: /pagamentos/",
        "Disallow: /*?*ordem=",
        "Allow: /",
        f"Sitemap: {settings.SITE_URL}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


def error_404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def error_500(request):
    return render(request, "errors/500.html", status=500)
