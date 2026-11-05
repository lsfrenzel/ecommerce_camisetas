import json
import logging

from django.conf import settings
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.orders.models import Order, OrderStatus, PaymentStatus

from .gateway import GatewayError, GatewayNotConfigured, verify_webhook_signature
from .models import PaymentEvent
from .services import reconcile_order, sync_payment

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def mercadopago_webhook(request):
    """
    Recebe notificações do Mercado Pago.

    1. Valida a assinatura (x-signature) com MERCADOPAGO_WEBHOOK_SECRET.
    2. Registra o evento com chave de idempotência.
    3. Consulta o pagamento NA API do Mercado Pago e só então atualiza o pedido.
    """
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        body = {}
    topic = request.GET.get("type") or request.GET.get("topic") or body.get("type") or body.get("topic") or ""
    data_id = request.GET.get("data.id") or (body.get("data") or {}).get("id") or request.GET.get("id") or ""
    data_id = str(data_id)
    request_id = request.headers.get("x-request-id", "")
    signature = request.headers.get("x-signature", "")
    secret = settings.MERCADOPAGO_WEBHOOK_SECRET

    signature_valid = verify_webhook_signature(secret=secret, x_signature=signature, x_request_id=request_id,
                                               data_id=data_id)
    if not signature_valid:
        if secret or not settings.DEBUG:
            logger.warning("Webhook Mercado Pago com assinatura inválida/ausente recusado")
            return JsonResponse({"error": "invalid signature"}, status=401)

    action = str(body.get("action") or "")[:60]
    key = f"{topic}:{data_id}:{action}:{request_id or body.get('id') or ''}"[:200]
    try:
        with transaction.atomic():
            event = PaymentEvent.objects.create(
                provider="mercadopago", idempotency_key=key, topic=topic[:40], action=action, resource_id=data_id[:60],
                payload={"type": topic, "action": action, "data_id": data_id, "live_mode": body.get("live_mode")},
                signature_valid=signature_valid,
            )
    except IntegrityError:
        event = PaymentEvent.objects.get(provider="mercadopago", idempotency_key=key)
        PaymentEvent.objects.filter(pk=event.pk).update(attempts=F("attempts") + 1)
        if event.processed:
            return JsonResponse({"status": "already processed"})

    if topic != "payment" or not data_id:
        event.processed = True
        event.processed_at = timezone.now()
        event.error = "tópico ignorado"
        event.save(update_fields=["processed", "processed_at", "error"])
        return JsonResponse({"status": "ignored"})

    try:
        sync_payment(data_id)
    except (GatewayError, GatewayNotConfigured) as exc:
        event.error = str(exc)[:255]
        event.save(update_fields=["error"])
        # 5xx faz o Mercado Pago reenviar a notificação mais tarde.
        return JsonResponse({"status": "retry"}, status=502)
    event.processed = True
    event.processed_at = timezone.now()
    event.error = ""
    event.save(update_fields=["processed", "processed_at", "error"])
    return JsonResponse({"status": "ok"})


@require_GET
def payment_return(request, public_id):
    """
    Retorno do checkout. Os parâmetros da URL NÃO são usados para aprovar nada:
    apenas disparam uma consulta server-side à API do Mercado Pago.
    """
    order = Order.objects.filter(public_id=public_id).first()
    if order is None:
        return redirect("core:home")
    payment_id = request.GET.get("payment_id") or request.GET.get("collection_id")
    if settings.MERCADOPAGO_ACCESS_TOKEN:
        try:
            if payment_id and payment_id.isdigit():
                sync_payment(payment_id)
            else:
                reconcile_order(order)
        except (GatewayError, GatewayNotConfigured):
            logger.warning("Não foi possível consultar o pagamento no retorno do pedido %s", order.number)
    order.refresh_from_db()
    if order.payment_status == PaymentStatus.APPROVED:
        messages.success(request, "Pagamento aprovado! Seu pedido já está com a gente.")
    elif order.payment_status in (PaymentStatus.PENDING, PaymentStatus.IN_PROCESS):
        messages.info(request, "Pagamento em processamento. Avisaremos por e-mail assim que for confirmado.")
    elif order.status == OrderStatus.AWAITING_PAYMENT:
        messages.warning(request, "O pagamento não foi concluído. Você pode tentar novamente.")
    url = order.get_absolute_url()
    if order.user_id is None:
        url += f"?t={order.access_token()}"
    return redirect(url)


def healthcheck_gateway(request):  # pragma: no cover - diagnóstico simples
    return HttpResponse("ok" if settings.MERCADOPAGO_ACCESS_TOKEN else "not configured")
