"""Criação e ciclo de vida de pedidos."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.cart.services import summarize
from apps.catalog.models import Product
from apps.catalog.pricing import PricingEngine
from apps.core.audit import log_action
from apps.core.models import AuditLog
from apps.core.utils import format_cep, format_cpf, money, only_digits
from apps.inventory import services as inventory
from apps.promotions.models import Coupon, CouponRedemption
from apps.promotions.services import CouponError, evaluate_coupon
from apps.shipping import services as shipping

from .models import ALLOWED_TRANSITIONS, Order, OrderItem, OrderStatus, OrderStatusHistory, PaymentStatus
from .notifications import notify_order

logger = logging.getLogger(__name__)


class CheckoutError(Exception):
    pass


@dataclass
class CheckoutData:
    email: str
    full_name: str
    phone: str
    cpf: str
    cep: str
    street: str
    number: str
    complement: str
    neighborhood: str
    city: str
    state: str
    shipping_code: str
    notes: str = ""


def create_order_from_cart(cart, data: CheckoutData, *, user=None) -> Order:
    """
    Converte o carrinho em pedido de forma atômica:
    revalida preços, estoque, cupom e frete no servidor, reserva o estoque e esvazia o carrinho.
    """
    if user is not None and not user.is_authenticated:
        user = None
    inventory.release_expired_reservations()

    with transaction.atomic():
        engine = PricingEngine()
        summary = summarize(cart, user=user, email=data.email, engine=engine)
        if summary.is_empty:
            raise CheckoutError("Seu carrinho está vazio.")

        # Trava variações e revalida estoque com valores atuais do banco.
        quantities: dict[int, int] = defaultdict(int)
        for line in summary.lines:
            quantities[line.variant.pk] += line.quantity
        variants = inventory.lock_variants(quantities.keys())
        for vid, qty in quantities.items():
            v = variants.get(vid)
            if v is None or not v.is_active or v.product.status != Product.Status.ACTIVE:
                raise CheckoutError("Um dos produtos do carrinho não está mais disponível.")
            if v.available < qty:
                raise CheckoutError(
                    f"{v.product.name} ({v.color.name}/{v.size.name}): só restam {v.available} unidade(s)."
                )

        for line in summary.lines:
            p = line.item.personalization
            if p is not None and p.status not in ("approved", "in_cart"):
                raise CheckoutError("Uma personalização do carrinho ainda não foi aprovada.")

        # Cupom — trava a linha do cupom para respeitar limites de uso sob concorrência.
        coupon_result = None
        if cart.coupon_id:
            coupon = Coupon.objects.select_for_update().get(pk=cart.coupon_id)
            try:
                coupon_result = evaluate_coupon(coupon, summary.priced_lines(), user=user, email=data.email)
            except CouponError as exc:
                raise CheckoutError(f"Cupom: {exc}") from exc

        # Frete — recotado no servidor; nunca confiamos no valor enviado pelo navegador.
        try:
            options = shipping.quote(data.cep, shipping.package_items_from_lines(summary.lines),
                                     summary.products_subtotal)
        except shipping.ShippingError as exc:
            raise CheckoutError(str(exc)) from exc
        option = shipping.find_option(options, data.shipping_code)
        if option is None:
            raise CheckoutError("Escolha uma opção de entrega válida para o CEP informado.")
        shipping_cost = Decimal("0.00") if (coupon_result and coupon_result.free_shipping) else option.price

        coupon_discount = coupon_result.discount if coupon_result else Decimal("0.00")
        subtotal = summary.subtotal_original
        total = money(summary.products_subtotal + summary.personalization_total - coupon_discount + shipping_cost)
        if total <= 0:
            raise CheckoutError("O valor total do pedido é inválido.")

        order = Order.objects.create(
            user=user,
            email=data.email.lower(),
            customer_name=data.full_name.strip(),
            phone=data.phone,
            cpf=format_cpf(data.cpf) if data.cpf else "",
            ship_recipient=data.full_name.strip(),
            ship_cep=format_cep(data.cep),
            ship_street=data.street,
            ship_number=data.number,
            ship_complement=data.complement,
            ship_neighborhood=data.neighborhood,
            ship_city=data.city,
            ship_state=data.state,
            shipping_method_id=option.method_id,
            shipping_option_code=option.code,
            shipping_name=option.name,
            shipping_days_max=option.days_max,
            shipping_cost=shipping_cost,
            subtotal=subtotal,
            promotion_discount=summary.promotion_discount,
            coupon_discount=coupon_discount,
            coupon_code=coupon_result.coupon.code if coupon_result else "",
            personalization_total=summary.personalization_total,
            total=total,
            customer_notes=data.notes[:1000],
        )
        for line in summary.lines:
            v = line.variant
            img = v.product.primary_image
            OrderItem.objects.create(
                order=order, variant=v, product=v.product, product_name=v.product.name, sku=v.sku,
                color_name=v.color.name, size_name=v.size.name, fit=v.get_fit_display(),
                category_name=v.product.category.name, image_url=img.thumb_url if img else "",
                original_unit_price=line.price.base, unit_price=line.price.final,
                unit_cost=v.product.cost_price, quantity=line.quantity,
                personalization=line.item.personalization, personalization_fee=line.personalization_fee,
                line_total=line.line_total,
            )
            if line.item.personalization_id:
                p = line.item.personalization
                p.status = "ordered"
                p.save(update_fields=["status", "updated_at"])

        order.reservation_expires_at = inventory.reserve_for_order(order, dict(quantities), variants)
        order.save(update_fields=["reservation_expires_at"])

        if coupon_result:
            CouponRedemption.objects.create(coupon=coupon_result.coupon, order=order, user=user,
                                            email=order.email, discount=coupon_discount)

        OrderStatusHistory.objects.create(order=order, to_status=order.status, note="Pedido criado")
        cart.items.all().delete()
        cart.coupon = None
        cart.save(update_fields=["coupon", "updated_at"])

    transaction.on_commit(lambda: notify_order(order, "created"))
    return order


def _add_history(order, from_status, to_status, note="", actor=None, notified=False):
    OrderStatusHistory.objects.create(order=order, from_status=from_status, to_status=to_status, note=note[:255],
                                      actor=actor, customer_notified=notified)


@transaction.atomic
def mark_paid(order: Order, *, note: str = "Pagamento aprovado", actor=None) -> bool:
    """Marca o pedido como pago (idempotente). Retorna True se houve mudança."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.payment_status == PaymentStatus.APPROVED and order.paid_at:
        return False
    previous = order.status
    order.payment_status = PaymentStatus.APPROVED
    order.paid_at = timezone.now()
    warnings = inventory.consume_for_paid_order(order)
    if previous in (OrderStatus.AWAITING_PAYMENT, OrderStatus.CANCELLED):
        has_custom = order.items.filter(personalization__isnull=False).exists()
        order.status = OrderStatus.CUSTOMIZING if has_custom else OrderStatus.PAID
    if previous == OrderStatus.CANCELLED or warnings:
        order.needs_attention = True
        reasons = []
        if previous == OrderStatus.CANCELLED:
            reasons.append("Pagamento aprovado após cancelamento/expiração")
        reasons.extend(warnings)
        order.attention_reason = "; ".join(reasons)[:255]
    order.save()
    for item in order.items.select_related("product"):
        if item.product_id:
            Product.objects.filter(pk=item.product_id).update(sold_count=F("sold_count") + item.quantity)
    _add_history(order, previous, order.status, note, actor=actor, notified=True)
    transaction.on_commit(lambda: notify_order(order, "paid"))
    return True


@transaction.atomic
def change_status(order: Order, new_status: str, *, actor=None, note: str = "", notify: bool = True,
                  request=None) -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk)
    if new_status == order.status:
        return order
    allowed = ALLOWED_TRANSITIONS.get(OrderStatus(order.status), set())
    if new_status not in allowed:
        raise CheckoutError(
            f"Transição inválida: {order.get_status_display()} → {OrderStatus(new_status).label}."
        )
    if new_status == OrderStatus.CANCELLED:
        return cancel_order(order, actor=actor, reason=note or "Cancelado pela equipe", request=request)
    previous = order.status
    order.status = new_status
    if new_status == OrderStatus.REFUNDED:
        order.payment_status = PaymentStatus.REFUNDED
    order.save()
    if new_status in (OrderStatus.SHIPPED, OrderStatus.DELIVERED):
        from apps.shipping.models import Shipment

        shipment, _ = Shipment.objects.get_or_create(order=order)
        now = timezone.now()
        if new_status == OrderStatus.SHIPPED:
            shipment.status = Shipment.Status.POSTED if shipment.status == Shipment.Status.PENDING else shipment.status
            shipment.posted_at = shipment.posted_at or now
        else:
            shipment.status = Shipment.Status.DELIVERED
            shipment.delivered_at = shipment.delivered_at or now
        shipment.save()
    _add_history(order, previous, new_status, note, actor=actor, notified=notify)
    log_action(actor=actor, action=AuditLog.Action.ORDER_STATUS, obj=order, request=request,
               changes={"status": [previous, new_status]}, message=note)
    if notify:
        transaction.on_commit(lambda: notify_order(order, "status"))
    return order


@transaction.atomic
def cancel_order(order: Order, *, actor=None, reason: str = "", restock: bool = True, request=None,
                 notify: bool = True) -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status in (OrderStatus.CANCELLED, OrderStatus.REFUNDED):
        return order
    if order.status in (OrderStatus.SHIPPED, OrderStatus.DELIVERED):
        raise CheckoutError("Pedidos enviados não podem ser cancelados; use reembolso/devolução.")
    previous = order.status
    inventory.release_reservations(order)
    if order.paid_at and restock:
        inventory.restock_order(order, user=actor, reason="Cancelamento")
    order.status = OrderStatus.CANCELLED
    if order.payment_status in (PaymentStatus.PENDING, PaymentStatus.IN_PROCESS, PaymentStatus.REJECTED):
        order.payment_status = PaymentStatus.CANCELLED
    order.cancelled_at = timezone.now()
    order.cancel_reason = reason[:255]
    if order.paid_at and order.payment_status == PaymentStatus.APPROVED:
        order.needs_attention = True
        order.attention_reason = "Pedido pago cancelado: efetue o reembolso no Mercado Pago."
    order.save()
    from apps.personalization.models import PersonalizationRequest

    PersonalizationRequest.objects.filter(order_items__order=order, status="ordered").update(status="approved")
    _add_history(order, previous, OrderStatus.CANCELLED, reason, actor=actor, notified=notify)
    if actor is not None:
        log_action(actor=actor, action=AuditLog.Action.ORDER_CANCEL, obj=order, request=request,
                   changes={"status": [previous, OrderStatus.CANCELLED]}, message=reason)
    if notify:
        transaction.on_commit(lambda: notify_order(order, "cancelled"))
    return order


def expire_order(order: Order) -> bool:
    """Cancela pedido não pago cuja reserva expirou."""
    if order.status != OrderStatus.AWAITING_PAYMENT or order.payment_status == PaymentStatus.IN_PROCESS:
        # Pagamento em análise: mantém a reserva até a resposta do gateway.
        if order.status != OrderStatus.AWAITING_PAYMENT:
            inventory.release_reservations(order)
        return False
    cancel_order(order, reason="Prazo de pagamento expirado", notify=True)
    return True


def orders_for_request(request):
    """Pedidos que o visitante atual pode ver (usuário autenticado ou pedidos da sessão)."""
    if request.user.is_authenticated:
        return Order.objects.filter(user=request.user)
    ids = request.session.get("guest_orders", [])
    return Order.objects.filter(public_id__in=ids, user__isnull=True)


def remember_guest_order(request, order):
    ids = request.session.get("guest_orders", [])
    if str(order.public_id) not in ids:
        ids.append(str(order.public_id))
    request.session["guest_orders"] = ids[-20:]


def normalize_phone(value: str) -> str:
    d = only_digits(value)
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return value
