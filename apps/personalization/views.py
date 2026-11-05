import json
import mimetypes
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.cart.models import CartItem
from apps.cart.services import get_cart
from apps.catalog.models import Product, ProductVariant
from apps.content.models import BrandSettings
from apps.core.ratelimit import rate_limited

from .forms import PersonalizationForm
from .models import PersonalizationRequest, PrintPlacement

SESSION_KEY = "my_personalizations"


def _owned(request, public_id) -> PersonalizationRequest:
    obj = PersonalizationRequest.objects.select_related("product", "variant__color", "variant__size", "placement"
                                                         ).filter(public_id=public_id).first()
    if obj is None:
        raise Http404
    if request.user.is_authenticated and (obj.user_id == request.user.pk or request.user.has_perm(
            "personalization.view_personalizationrequest")):
        return obj
    if obj.user_id is None and str(obj.public_id) in request.session.get(SESSION_KEY, []):
        return obj
    raise Http404


def start(request):
    brand = BrandSettings.load()
    form = PersonalizationForm(request.POST or None, request.FILES or None, user=request.user,
                               initial={"product": request.GET.get("modelo")})
    if request.method == "POST":
        if rate_limited(request, "personalize", limit=10, window=3600):
            messages.error(request, "Muitas solicitações em pouco tempo. Tente novamente mais tarde.")
        elif form.is_valid():
            with transaction.atomic():
                obj = form.save(commit=False)
                obj.user = request.user if request.user.is_authenticated else None
                obj.session_key = request.session.session_key or ""
                obj.fee = obj.placement.fee
                obj.rights_confirmed = True
                if form.processed:
                    obj.image.save(form.processed.content.name, form.processed.content, save=False)
                    obj.image_width, obj.image_height = form.processed.width, form.processed.height
                    obj.image_original_name = getattr(form, "_original_name", "")
                    obj.low_resolution = max(obj.image_width, obj.image_height) < brand.personalization_min_pixels
                obj.status = (PersonalizationRequest.Status.SUBMITTED if brand.personalization_requires_approval
                              else PersonalizationRequest.Status.APPROVED)
                obj.save()
            ids = request.session.get(SESSION_KEY, [])
            ids.append(str(obj.public_id))
            request.session[SESSION_KEY] = ids[-20:]
            if obj.status == PersonalizationRequest.Status.APPROVED:
                _add_to_cart(request, obj)
                messages.success(request, "Personalização adicionada ao carrinho.")
                return redirect("cart:detail")
            messages.success(request, "Recebemos sua personalização! Nossa equipe vai analisar e avisar por e-mail.")
            return redirect(obj.get_absolute_url())

    products = Product.objects.visible().filter(is_customizable=True).prefetch_related("images")
    variants = ProductVariant.objects.filter(product__in=products, is_active=True).select_related("color", "size")
    placements = PrintPlacement.objects.filter(is_active=True)
    data = {
        "products": [{"id": p.pk, "name": p.name, "price": str(p.price),
                      "front": next((i.thumb_url for i in p.images.all() if i.view == "front"), ""),
                      "back": next((i.thumb_url for i in p.images.all() if i.view == "back"), "")} for p in products],
        "variants": [{"id": v.pk, "product": v.product_id, "label": f"{v.color.name} · {v.size.name} · {v.get_fit_display()}",
                      "hex": v.color.hex, "available": v.available} for v in variants],
        "placements": [{"id": pl.pk, "name": pl.name, "side": pl.side, "fee": str(pl.fee), "box": [
            pl.box_left, pl.box_top, pl.box_width, pl.box_height]} for pl in placements],
        "minPixels": brand.personalization_min_pixels,
    }
    return render(request, "personalization/start.html", {
        "form": form, "data_json": json.dumps(data), "placements": placements, "has_products": products.exists(),
    })


def detail(request, public_id):
    obj = _owned(request, public_id)
    return render(request, "personalization/detail.html", {"p": obj, "section": "personalization"})


@login_required
def mine(request):
    items = request.user.personalizations.select_related("product", "placement", "variant__color", "variant__size")
    return render(request, "personalization/mine.html", {"items": items, "section": "personalization"})


def _add_to_cart(request, obj):
    cart = get_cart(request, create=True)
    CartItem.objects.update_or_create(personalization=obj, defaults={"cart": cart, "variant": obj.variant,
                                                                       "quantity": obj.quantity})
    obj.status = PersonalizationRequest.Status.IN_CART
    obj.save(update_fields=["status", "updated_at"])


@require_POST
def add_to_cart(request, public_id):
    obj = _owned(request, public_id)
    if not obj.can_add_to_cart:
        messages.error(request, "Esta personalização ainda não está liberada para compra.")
        return redirect(obj.get_absolute_url())
    if obj.variant.available < obj.quantity:
        messages.error(request, "A base escolhida está sem estoque suficiente. Fale com a gente.")
        return redirect(obj.get_absolute_url())
    _add_to_cart(request, obj)
    messages.success(request, "Personalização adicionada ao carrinho.")
    return redirect("cart:detail")


def artwork(request, public_id):
    """Entrega a arte privada somente ao dono ou à equipe autorizada."""
    obj = _owned(request, public_id)
    if not obj.image:
        raise Http404
    storage = obj.image.storage
    if hasattr(storage, "bucket_name"):
        # S3: URL assinada de curta duração (5 min).
        return HttpResponseRedirect(storage.url(obj.image.name))
    content_type = mimetypes.guess_type(obj.image.name)[0] or "application/octet-stream"
    response = FileResponse(storage.open(obj.image.name, "rb"), content_type=content_type)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    if request.GET.get("download"):
        response["Content-Disposition"] = f'attachment; filename="personalizacao-{str(obj.public_id)[:8]}{Path(obj.image.name).suffix}"'
    return response
