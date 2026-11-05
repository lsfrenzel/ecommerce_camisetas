import json
import logging

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.catalog.models import ProductVariant
from apps.core.ratelimit import rate_limited
from apps.orders.services import CheckoutError, create_order_from_cart, remember_guest_order
from apps.payments.gateway import GatewayError, GatewayNotConfigured
from apps.promotions.services import CouponError, evaluate_coupon, find_coupon
from apps.shipping import services as shipping

from .forms import CheckoutForm
from .services import CartError, add_item, get_cart, remove_item, summarize, update_quantity

logger = logging.getLogger(__name__)


def _is_htmx(request):
    return bool(request.headers.get("HX-Request"))


def _with_cart_trigger(response, cart):
    count = sum(cart.items.values_list("quantity", flat=True)) if cart else 0
    response["HX-Trigger"] = json.dumps({"cart:updated": {"count": count}})
    return response


def cart_detail(request):
    cart = get_cart(request)
    summary = summarize(cart, user=request.user)
    options, ship_error = [], ""
    if cart and cart.shipping_cep and not summary.is_empty:
        try:
            options = shipping.quote(cart.shipping_cep, shipping.package_items_from_lines(summary.lines),
                                     summary.products_subtotal)
            chosen = shipping.find_option(options, cart.shipping_choice) or (options[0] if options else None)
            if chosen:
                summary.shipping_cost = chosen.price
                cart.shipping_choice = chosen.code
        except shipping.ShippingError as exc:
            ship_error = str(exc)
    context = {"summary": summary, "cart": cart, "options": options, "ship_error": ship_error}
    if _is_htmx(request) and request.headers.get("HX-Target") == "cart-body":
        return render(request, "cart/_cart_body.html", context)
    return render(request, "cart/detail.html", context)


@require_POST
def cart_add(request):
    variant = ProductVariant.objects.select_related("product").filter(pk=request.POST.get("variant_id") or 0).first()
    try:
        quantity = int(request.POST.get("quantity", 1))
    except ValueError:
        quantity = 1
    buy_now = request.POST.get("buy_now") == "1" or request.GET.get("buy_now") == "1"
    error = ""
    cart = None
    if variant is None:
        error = "Selecione cor e tamanho."
    else:
        cart = get_cart(request, create=True)
        try:
            add_item(cart, variant, quantity)
        except CartError as exc:
            error = str(exc)
    if _is_htmx(request):
        if not error and buy_now:
            response = HttpResponse(status=204)
            response["HX-Redirect"] = reverse("cart:checkout")
            return response
        response = render(request, "cart/_added.html", {"error": error, "variant": variant, "quantity": quantity})
        return _with_cart_trigger(response, cart) if not error else response
    if error:
        messages.error(request, error)
        return redirect(variant.product.get_absolute_url() if variant else "catalog:shop")
    if buy_now:
        return redirect("cart:checkout")
    messages.success(request, "Produto adicionado ao carrinho.")
    return redirect("cart:detail")


@require_POST
def cart_update(request, item_id):
    cart = get_cart(request)
    if cart is None:
        return redirect("cart:detail")
    try:
        update_quantity(cart, item_id, int(request.POST.get("quantity", 1)))
    except (CartError, ValueError) as exc:
        messages.error(request, str(exc) if isinstance(exc, CartError) else "Quantidade inválida.")
    if _is_htmx(request):
        return _with_cart_trigger(cart_detail(request), cart)
    return redirect("cart:detail")


@require_POST
def cart_remove(request, item_id):
    cart = get_cart(request)
    if cart is not None:
        remove_item(cart, item_id)
    if _is_htmx(request):
        return _with_cart_trigger(cart_detail(request), cart)
    return redirect("cart:detail")


@require_POST
def apply_coupon(request):
    cart = get_cart(request)
    if cart is None:
        return redirect("cart:detail")
    if rate_limited(request, "coupon", limit=15, window=600):
        messages.error(request, "Muitas tentativas de cupom. Aguarde alguns minutos.")
    else:
        code = request.POST.get("code", "")
        coupon = find_coupon(code)
        summary = summarize(cart, user=request.user)
        try:
            evaluate_coupon(coupon, summary.priced_lines(), user=request.user,
                            email=request.user.email if request.user.is_authenticated else "")
            cart.coupon = coupon
            cart.save(update_fields=["coupon", "updated_at"])
            messages.success(request, f"Cupom {coupon.code} aplicado.")
        except CouponError as exc:
            messages.error(request, str(exc))
    if _is_htmx(request):
        return cart_detail(request)
    return redirect(request.POST.get("next") or "cart:detail")


@require_POST
def remove_coupon(request):
    cart = get_cart(request)
    if cart is not None:
        cart.coupon = None
        cart.save(update_fields=["coupon", "updated_at"])
    if _is_htmx(request):
        return cart_detail(request)
    return redirect(request.POST.get("next") or "cart:detail")


@require_POST
def set_shipping(request):
    cart = get_cart(request)
    if cart is not None:
        from apps.core.utils import format_cep, only_digits

        cep = only_digits(request.POST.get("cep", ""))
        if cep:
            cart.shipping_cep = format_cep(cep)
        if request.POST.get("shipping_code"):
            cart.shipping_choice = request.POST["shipping_code"][:40]
        cart.save(update_fields=["shipping_cep", "shipping_choice", "updated_at"])
    if _is_htmx(request):
        return cart_detail(request)
    return redirect("cart:detail")


def checkout(request):
    cart = get_cart(request)
    summary = summarize(cart, user=request.user)
    if summary.is_empty:
        messages.info(request, "Seu carrinho está vazio.")
        return redirect("cart:detail")

    gateway_ready = bool(settings.MERCADOPAGO_ACCESS_TOKEN) or settings.ALLOW_ORDERS_WITHOUT_GATEWAY
    initial = {}
    if request.user.is_authenticated:
        profile = getattr(request.user, "profile", None)
        initial = {"email": request.user.email, "full_name": request.user.full_name,
                   "phone": profile.phone if profile else "", "cpf": profile.cpf if profile else ""}
        address = request.user.addresses.first()
        if address:
            initial.update({"cep": address.cep, "street": address.street, "number": address.number,
                            "complement": address.complement, "neighborhood": address.neighborhood,
                            "city": address.city, "state": address.state})
    if cart.shipping_cep and "cep" not in initial:
        initial["cep"] = cart.shipping_cep
    if cart.shipping_choice:
        initial["shipping_code"] = cart.shipping_choice

    form = CheckoutForm(request.POST or None, initial=initial, user=request.user)
    options, ship_error = [], ""
    cep_for_quote = (request.POST.get("cep") if request.method == "POST" else initial.get("cep")) or ""
    if cep_for_quote:
        try:
            options = shipping.quote(cep_for_quote, shipping.package_items_from_lines(summary.lines),
                                     summary.products_subtotal)
        except shipping.ShippingError as exc:
            ship_error = str(exc)
    chosen = shipping.find_option(options, request.POST.get("shipping_code") or initial.get("shipping_code", ""))
    if chosen:
        summary.shipping_cost = chosen.price

    if request.method == "POST":
        if not gateway_ready:
            messages.error(request, "Pagamentos ainda não configurados nesta loja.")
        elif summary.has_problems:
            messages.error(request, "Ajuste os itens indisponíveis do carrinho antes de finalizar.")
            return redirect("cart:detail")
        elif rate_limited(request, "checkout", limit=20, window=600):
            messages.error(request, "Muitas tentativas. Aguarde alguns minutos.")
        elif form.is_valid():
            try:
                order = create_order_from_cart(cart, form.to_checkout_data(), user=request.user)
            except CheckoutError as exc:
                messages.error(request, str(exc))
            else:
                form.save_to_profile(request.user)
                remember_guest_order(request, order)
                if settings.MERCADOPAGO_ACCESS_TOKEN:
                    from apps.payments.services import start_checkout

                    try:
                        return redirect(start_checkout(order))
                    except (GatewayError, GatewayNotConfigured) as exc:
                        logger.warning("Falha ao iniciar pagamento do pedido %s", order.number)
                        messages.error(request, str(exc))
                messages.info(request, "Pedido registrado e aguardando pagamento.")
                return redirect(order.get_absolute_url() + (f"?t={order.access_token()}" if not order.user_id else ""))

    return render(request, "cart/checkout.html", {
        "form": form, "summary": summary, "options": options, "chosen": chosen, "ship_error": ship_error,
        "gateway_ready": gateway_ready, "gateway_configured": bool(settings.MERCADOPAGO_ACCESS_TOKEN),
    })


def checkout_shipping(request):
    """Parcial HTMX: opções de frete do checkout para o CEP digitado."""
    cart = get_cart(request)
    summary = summarize(cart, user=request.user)
    options, ship_error = [], ""
    cep = request.GET.get("cep", "")
    try:
        options = shipping.quote(cep, shipping.package_items_from_lines(summary.lines), summary.products_subtotal)
    except shipping.ShippingError as exc:
        ship_error = str(exc)
    selected = request.GET.get("shipping_code", "")
    chosen = shipping.find_option(options, selected) or (options[0] if options else None)
    if chosen:
        summary.shipping_cost = chosen.price
    return render(request, "cart/_checkout_shipping.html", {
        "options": options, "ship_error": ship_error, "chosen": chosen, "summary": summary, "cep": cep,
    })
