"""
Processamento de pagamentos.

Regras centrais:
- O status de um pedido só muda com base em dados obtidos DIRETAMENTE da API do gateway
  (nunca a partir de parâmetros da URL de retorno ou do corpo de um webhook).
- Processamento idempotente: aplicar o mesmo pagamento várias vezes não muda o resultado.
- Valor, moeda, referência e modo (teste/produção) são conferidos antes de aprovar.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.core.audit import log_action
from apps.core.models import AuditLog
from apps.orders.models import Order, OrderStatus, PaymentStatus
from apps.orders.services import _add_history, mark_paid

from .gateway import GatewayError, get_gateway, to_decimal
from .models import Payment

logger = logging.getLogger(__name__)

SAFE_FIELDS = (
    "id", "status", "status_detail", "payment_method_id", "payment_type_id", "installments",
    "transaction_amount", "currency_id", "date_created", "date_approved", "live_mode", "external_reference",
)

STATUS_MAP = {
    "pending": PaymentStatus.PENDING,
    "authorized": PaymentStatus.IN_PROCESS,
    "in_process": PaymentStatus.IN_PROCESS,
    "in_mediation": PaymentStatus.IN_PROCESS,
    "approved": PaymentStatus.APPROVED,
    "rejected": PaymentStatus.REJECTED,
    "cancelled": PaymentStatus.CANCELLED,
    "refunded": PaymentStatus.REFUNDED,
    "charged_back": PaymentStatus.CHARGED_BACK,
}


def start_checkout(order: Order) -> str:
    """Cria a preferência no Mercado Pago e retorna a URL do checkout oficial."""
    gateway = get_gateway()
    preference = gateway.create_preference(order)
    Payment.objects.create(
        order=order, provider=Payment.Provider.MERCADOPAGO, preference_id=preference["id"],
        checkout_url=preference["url"] or "", amount=order.total, status="created",
        live_mode=gateway.is_production,
    )
    return preference["url"]


def sync_payment(payment_id: str) -> Order | None:
    """Busca o pagamento na API do gateway e aplica ao pedido."""
    data = get_gateway().get_payment(str(payment_id))
    return apply_gateway_payment(data)


def reconcile_order(order: Order) -> Order:
    """Consulta todos os pagamentos do pedido no gateway (reconciliação)."""
    for data in get_gateway().search_by_reference(str(order.public_id)):
        apply_gateway_payment(data)
    order.refresh_from_db()
    return order


@transaction.atomic
def apply_gateway_payment(data: dict) -> Order | None:
    reference = str(data.get("external_reference") or "")
    payment_id = str(data.get("id") or "")
    if not reference or not payment_id:
        logger.warning("Pagamento sem referência ignorado")
        return None
    order = Order.objects.select_for_update().filter(public_id=reference).first() if _is_uuid(reference) else None
    if order is None:
        logger.warning("Pagamento %s com referência desconhecida", payment_id)
        return None

    gw_status = str(data.get("status") or "")
    mapped = STATUS_MAP.get(gw_status, PaymentStatus.PENDING)
    amount = to_decimal(data.get("transaction_amount"))
    approved_at = parse_datetime(data["date_approved"]) if data.get("date_approved") else None

    payment, _ = Payment.objects.select_for_update().get_or_create(
        provider=Payment.Provider.MERCADOPAGO, external_id=payment_id,
        defaults={"order": order, "amount": amount},
    )
    if payment.order_id != order.pk:
        logger.error("Pagamento %s já vinculado a outro pedido", payment_id)
        return None
    payment.status = gw_status
    payment.status_detail = str(data.get("status_detail") or "")[:80]
    payment.method = str(data.get("payment_type_id") or data.get("payment_method_id") or "")[:40]
    payment.installments = data.get("installments") or None
    payment.amount = amount
    payment.live_mode = bool(data.get("live_mode"))
    payment.approved_at = approved_at
    details = data.get("transaction_details") or {}
    if details.get("net_received_amount") is not None:
        payment.amount_received = to_decimal(details.get("net_received_amount"))
        payment.fee_amount = amount - payment.amount_received
    payment.raw = {k: data.get(k) for k in SAFE_FIELDS if k in data}
    payment.save()

    problems = []
    if str(data.get("currency_id") or "BRL") != "BRL":
        problems.append("moeda diferente de BRL")
    if abs(amount - order.total) > to_decimal("0.01"):
        problems.append(f"valor pago ({amount}) difere do total ({order.total})")
    if settings.MERCADOPAGO_ENVIRONMENT == "production" and not data.get("live_mode", False):
        problems.append("pagamento de teste recebido em produção")

    if mapped == PaymentStatus.APPROVED:
        if problems:
            order.needs_attention = True
            order.attention_reason = ("Pagamento aprovado não conferido: " + "; ".join(problems))[:255]
            order.payment_status = PaymentStatus.IN_PROCESS
            order.save(update_fields=["needs_attention", "attention_reason", "payment_status", "updated_at"])
            logger.error("Pagamento %s não conferido: %s", payment_id, problems)
            return order
        mark_paid(order, note=f"Pagamento aprovado no Mercado Pago (#{payment_id})")
    elif mapped in (PaymentStatus.REFUNDED, PaymentStatus.CHARGED_BACK):
        if order.payment_status == PaymentStatus.APPROVED and order.status != OrderStatus.REFUNDED:
            previous = order.status
            order.payment_status = mapped
            order.status = OrderStatus.REFUNDED
            order.needs_attention = True
            order.attention_reason = "Pagamento estornado/contestado: avalie devolução ao estoque."
            order.save()
            _add_history(order, previous, OrderStatus.REFUNDED, f"Pagamento {gw_status} no Mercado Pago")
    else:
        # Não rebaixa um pedido já aprovado por causa de tentativas anteriores recusadas.
        if order.payment_status != PaymentStatus.APPROVED:
            order.payment_status = mapped
            order.save(update_fields=["payment_status", "updated_at"])
    order.refresh_from_db()
    return order


@transaction.atomic
def register_manual_payment(order: Order, *, actor, note: str, request=None) -> Order:
    """Pagamento recebido fora do gateway (ex.: Pix direto), registrado pela equipe com auditoria."""
    if order.status != OrderStatus.AWAITING_PAYMENT and order.status != OrderStatus.CANCELLED:
        raise GatewayError("O pedido não está aguardando pagamento.")
    Payment.objects.create(order=order, provider=Payment.Provider.MANUAL, status="approved", amount=order.total,
                           approved_at=timezone.now(), raw={"note": note[:200], "by": actor.email})
    mark_paid(order, note=f"Pagamento manual registrado: {note}"[:255], actor=actor)
    log_action(actor=actor, action=AuditLog.Action.PAYMENT, obj=order, request=request,
               message=f"Pagamento manual: {note}"[:255])
    order.refresh_from_db()
    return order


def _is_uuid(value: str) -> bool:
    import uuid

    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


__all__ = ["start_checkout", "sync_payment", "reconcile_order", "apply_gateway_payment",
           "register_manual_payment", "GatewayError"]
