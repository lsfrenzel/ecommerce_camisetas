"""Notificações por e-mail ao cliente. Falhas de envio nunca quebram o fluxo de compra."""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger(__name__)

SUBJECTS = {
    "created": "Recebemos seu pedido #{number}",
    "paid": "Pagamento aprovado — pedido #{number}",
    "status": "Atualização do pedido #{number}: {status}",
    "cancelled": "Pedido #{number} cancelado",
}


def order_link(order) -> str:
    path = reverse("orders:detail", args=[order.public_id])
    if order.user_id is None:
        path += f"?t={order.access_token()}"
    return f"{settings.SITE_URL}{path}"


def send_templated(to: str, subject: str, template: str, context: dict) -> bool:
    from apps.content.models import BrandSettings

    brand = BrandSettings.load()
    context = {**context, "brand": brand, "site_url": settings.SITE_URL}
    text = render_to_string(f"emails/{template}.txt", context)
    html = render_to_string(f"emails/{template}.html", context)
    message = EmailMultiAlternatives(subject=f"{brand.store_name} · {subject}", body=text,
                                     from_email=settings.DEFAULT_FROM_EMAIL, to=[to])
    message.attach_alternative(html, "text/html")
    try:
        message.send()
        return True
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao enviar e-mail '%s'", template)
        return False


def notify_order(order, kind: str) -> bool:
    order.refresh_from_db()
    subject = SUBJECTS[kind].format(number=order.number, status=order.get_status_display())
    shipment = getattr(order, "shipment", None) if hasattr(order, "shipment") else None
    return send_templated(order.email, subject, "order_update", {
        "order": order, "kind": kind, "link": order_link(order), "shipment": shipment,
        "items": order.items.all(),
    })
