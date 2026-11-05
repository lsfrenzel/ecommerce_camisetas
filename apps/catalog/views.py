import json
from decimal import Decimal, InvalidOperation

from django.core.paginator import Paginator
from django.db.models import Case, DecimalField, Exists, F, OuterRef, Prefetch, Q, When
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.catalog.pricing import PricingEngine, installments_text

from .models import Category, Collection, Color, Product, ProductImage, ProductVariant, Size

SORTS = {
    "novidades": ("-created_at", "Novidades"),
    "populares": ("-sold_count", "Mais vendidos"),
    "menor-preco": ("list_price", "Menor preço"),
    "maior-preco": ("-list_price", "Maior preço"),
}
PAGE_SIZE = 12


def _base_queryset():
    now = timezone.now()
    active_sale = (
        Q(sale_price__isnull=False, sale_price__lt=F("price"))
        & (Q(sale_starts_at__isnull=True) | Q(sale_starts_at__lte=now))
        & (Q(sale_ends_at__isnull=True) | Q(sale_ends_at__gte=now))
    )
    in_stock = ProductVariant.objects.filter(product=OuterRef("pk"), is_active=True, stock__gt=F("reserved"))
    return (
        Product.objects.visible()
        .select_related("category")
        .prefetch_related(Prefetch("images", queryset=ProductImage.objects.order_by("position", "id")), "collections")
        .annotate(
            list_price=Case(When(active_sale, then=F("sale_price")), default=F("price"),
                            output_field=DecimalField(max_digits=10, decimal_places=2)),
            in_stock=Exists(in_stock),
        )
    )


def _decimal(value):
    try:
        return Decimal(value.replace(",", ".")) if value else None
    except (InvalidOperation, AttributeError):
        return None


def shop(request, category_slug=None, collection_slug=None):
    qs = _base_queryset()
    category = collection = None
    if category_slug:
        category = get_object_or_404(Category, slug=category_slug, is_active=True)
        qs = qs.filter(Q(category=category) | Q(category__parent=category))
    if collection_slug:
        collection = get_object_or_404(Collection, slug=collection_slug, is_active=True)
        qs = qs.filter(collections=collection)

    params = request.GET
    q = params.get("q", "").strip()[:80]
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(sku_base__icontains=q) | Q(variants__sku__iexact=q)
            | Q(category__name__icontains=q) | Q(collections__name__icontains=q)
            | Q(short_description__icontains=q)
        )
    selected_categories = params.getlist("categoria")
    if selected_categories:
        qs = qs.filter(category__slug__in=selected_categories)
    selected_collections = params.getlist("colecao")
    if selected_collections:
        qs = qs.filter(collections__slug__in=selected_collections)
    selected_colors = params.getlist("cor")
    selected_sizes = params.getlist("tamanho")
    fit = params.get("modelagem", "")
    only_available = params.get("disponivel") == "1"
    if selected_colors or selected_sizes or fit:
        variant_q = Q(is_active=True)
        if selected_colors:
            variant_q &= Q(color__slug__in=selected_colors)
        if selected_sizes:
            variant_q &= Q(size__name__in=selected_sizes)
        if fit in ("oversized", "regular"):
            variant_q &= Q(fit=fit)
        if only_available:
            variant_q &= Q(stock__gt=F("reserved"))
        qs = qs.filter(Exists(ProductVariant.objects.filter(variant_q, product=OuterRef("pk"))))
    elif only_available:
        qs = qs.filter(in_stock=True)
    price_min, price_max = _decimal(params.get("preco_min")), _decimal(params.get("preco_max"))
    if price_min is not None:
        qs = qs.filter(list_price__gte=price_min)
    if price_max is not None:
        qs = qs.filter(list_price__lte=price_max)

    sort = params.get("ordem", "novidades")
    if sort not in SORTS:
        sort = "novidades"
    qs = qs.distinct().order_by(SORTS[sort][0], "-id")

    paginator = Paginator(qs, PAGE_SIZE)
    page = paginator.get_page(params.get("page"))
    PricingEngine().annotate(page.object_list)

    title = "Camisetas"
    if fit == "oversized":
        title = "Oversized"
    if category:
        title = category.name
    if collection:
        title = collection.name
    if q:
        title = f"Busca: “{q}”"

    active_filters = bool(selected_categories or selected_collections or selected_colors or selected_sizes
                          or fit or only_available or price_min or price_max)
    context = {
        "page": page,
        "products": page.object_list,
        "title": title,
        "category": category,
        "collection": collection,
        "q": q,
        "sorts": [(k, v[1]) for k, v in SORTS.items()],
        "sort": sort,
        "categories": Category.objects.filter(is_active=True),
        "collections": Collection.objects.filter(is_active=True),
        "colors": Color.objects.filter(variants__product__status=Product.Status.ACTIVE).distinct(),
        "sizes": Size.objects.filter(variants__product__status=Product.Status.ACTIVE).distinct(),
        "selected_categories": selected_categories,
        "selected_collections": selected_collections,
        "selected_colors": selected_colors,
        "selected_sizes": selected_sizes,
        "fit": fit,
        "only_available": only_available,
        "price_min": params.get("preco_min", ""),
        "price_max": params.get("preco_max", ""),
        "active_filters": active_filters,
    }
    if request.headers.get("HX-Request") and request.headers.get("HX-Target") == "product-results":
        return render(request, "catalog/_results.html", context)
    return render(request, "catalog/shop.html", context)


def collections(request):
    items = Collection.objects.filter(is_active=True).prefetch_related("products")
    return render(request, "catalog/collections.html", {"collections": items})


def product_detail(request, slug):
    qs = Product.objects.select_related("category", "size_chart").prefetch_related(
        Prefetch("images", queryset=ProductImage.objects.select_related("color").order_by("position", "id")),
        "collections",
        Prefetch("variants", queryset=ProductVariant.objects.filter(is_active=True).select_related("color", "size")),
    )
    product = get_object_or_404(qs, slug=slug)
    if not product.is_visible and not (request.user.is_authenticated and request.user.is_staff):
        raise Http404
    engine = PricingEngine()
    price = engine.price_for(product)
    variants = list(product.variants.all())
    variant_data = []
    for v in variants:
        p = engine.price_for(product, v)
        variant_data.append({
            "id": v.pk, "color": v.color.slug, "size": v.size.name, "fit": v.fit, "available": v.available,
            "sku": v.sku, "price": str(p.final), "base": str(p.base), "low": 0 < v.available <= v.low_stock_threshold,
        })
    colors, sizes, fits = [], [], []
    for v in variants:
        if v.color not in colors:
            colors.append(v.color)
        if v.size not in sizes:
            sizes.append(v.size)
        if v.fit not in [f[0] for f in fits]:
            fits.append((v.fit, v.get_fit_display()))
    sizes.sort(key=lambda s: s.position)
    images = list(product.images.all())
    image_data = [
        {"url": img.image.url, "thumb": img.thumb_url, "alt": img.alt_text, "color": img.color.slug if img.color else "",
         "w": img.width or 1200, "h": img.height or 1500, "illustrative": img.is_illustrative}
        for img in images
    ]
    related = list(
        _base_queryset().filter(Q(category=product.category) | Q(collections__in=product.collections.all()))
        .exclude(pk=product.pk).distinct().order_by("-sold_count", "-created_at")[:4]
    )
    engine.annotate(related)
    from apps.content.models import BrandSettings

    brand = BrandSettings.load()
    context = {
        "product": product,
        "price": price,
        "installments": installments_text(price.final, brand),
        "variants_json": json.dumps(variant_data),
        "images_json": json.dumps(image_data),
        "images": images,
        "colors": colors,
        "sizes": sizes,
        "fits": fits,
        "related": related,
        "any_available": any(v.available > 0 for v in variants),
        "default_color": colors[0].slug if colors else "",
        "default_fit": fits[0][0] if fits else "",
    }
    return render(request, "catalog/product_detail.html", context)
