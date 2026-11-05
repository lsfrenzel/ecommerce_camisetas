import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .models import Order
from .services import remember_guest_order

logger = logging.getLogger(__name__)


def _get_order_for_request(request, public_id) -> Order:
    """Garante que somente o dono (ou portador do link assinado) acesse o pedido."""
    order = Order.objects.filter(public_id=public_id).select_related("shipment").first()
    if order is None:
        raise Http404
    user = request.user
    if user.is_authenticated and order.user_id == user.pk:
        return order
    if order.user_id is None:
        token = request.GET.get("t", "")
        if token and Order.check_access_token(token, order.public_id):
            remember_guest_order(request, order)
            return order
        if str(order.public_id) in request.session.get("guest_orders", []):
            return order
    raise Http404


@login_required
def order_list(request):
    orders = request.user.orders.prefetch_related("items").order_by("-created_at")
    return render(request, "orders/list.html", {"orders": orders})


def order_detail(request, public_id):
    order = _get_order_for_request(request, public_id)
    return render(request, "orders/detail.html", {
        "order": order,
        "items": order.items.select_related("personalization"),
        "history": order.history.all(),
        "shipment": getattr(order, "shipment", None) if hasattr(order, "shipment") else None,
        "gateway_configured": bool(settings.MERCADOPAGO_ACCESS_TOKEN),
        "guest_token": order.access_token() if order.user_id is None else "",
    })


@require_POST
def order_pay(request, public_id):
    """Gera um novo link de pagamento para um pedido ainda não pago."""
    order = _get_order_for_request(request, public_id)
    if not order.can_pay:
        messages.info(request, "Este pedido não está aguardando pagamento.")
        return redirect(order.get_absolute_url())
    if not settings.MERCADOPAGO_ACCESS_TOKEN:
        messages.error(request, "Pagamento online indisponível no momento.")
        return redirect(order.get_absolute_url())
    from apps.payments.gateway import GatewayError
    from apps.payments.services import start_checkout

    try:
        return redirect(start_checkout(order))
    except GatewayError as exc:
        messages.error(request, str(exc))
        return redirect(order.get_absolute_url())
