from decimal import Decimal

from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.catalog.models import ProductVariant
from apps.catalog.pricing import PricingEngine
from apps.core.ratelimit import rate_limited

from . import services


@require_POST
def quote_view(request):
    """Simulação de frete na página de produto (HTMX)."""
    error = ""
    options = []
    if rate_limited(request, "ship-quote", limit=40, window=600):
        error = "Muitas consultas. Aguarde alguns minutos."
    else:
        variant = ProductVariant.objects.select_related("product").filter(pk=request.POST.get("variant_id") or 0).first()
        try:
            qty = max(1, min(int(request.POST.get("quantity", 1)), 20))
        except ValueError:
            qty = 1
        if variant is None:
            error = "Produto inválido."
        else:
            price = PricingEngine().price_for(variant.product, variant).final
            p = variant.product
            items = [services.PackageItem(product_id=p.pk, quantity=qty, unit_price=price, weight_grams=p.weight_grams,
                                          length_cm=p.length_cm, width_cm=p.width_cm, height_cm=p.height_cm)]
            try:
                options = services.quote(request.POST.get("cep", ""), items, price * Decimal(qty))
            except services.ShippingError as exc:
                error = str(exc)
    return render(request, "shipping/_quote.html", {"options": options, "error": error})
