"""
Adaptador do Mercado Pago (Checkout Pro).

Documentação: https://www.mercadopago.com.br/developers/pt/docs/checkout-pro
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)


class GatewayNotConfigured(Exception):
    pass


class GatewayError(Exception):
    pass


class MercadoPagoGateway:
    name = "mercadopago"

    def __init__(self, access_token: str | None = None, environment: str | None = None):
        self.access_token = access_token if access_token is not None else settings.MERCADOPAGO_ACCESS_TOKEN
        self.environment = (environment or settings.MERCADOPAGO_ENVIRONMENT or "sandbox").lower()
        self._sdk = None

    @property
    def configured(self) -> bool:
        return bool(self.access_token)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def sdk(self):
        if not self.configured:
            raise GatewayNotConfigured("MERCADOPAGO_ACCESS_TOKEN não configurado.")
        if self._sdk is None:
            import mercadopago

            self._sdk = mercadopago.SDK(self.access_token)
        return self._sdk

    # ------------------------------------------------------------------
    def build_preference(self, order) -> dict:
        site = settings.SITE_URL
        is_https = site.startswith("https://")
        return_url = site + reverse("payments:return", args=[order.public_id])
        items_total = order.total - order.shipping_cost
        if order.coupon_discount > 0:
            # O Mercado Pago não aceita itens negativos: com cupom, enviamos um item consolidado.
            items = [{
                "id": order.number,
                "title": f"Pedido #{order.number} ({sum(i.quantity for i in order.items.all())} item(ns))",
                "quantity": 1,
                "unit_price": float(items_total),
                "currency_id": "BRL",
            }]
        else:
            items = [
                {
                    "id": item.sku,
                    "title": f"{item.product_name} — {item.color_name} {item.size_name}"[:250],
                    "quantity": item.quantity,
                    "unit_price": float(item.unit_price + item.personalization_fee),
                    "currency_id": "BRL",
                    "picture_url": (site + item.image_url) if item.image_url.startswith("/") else item.image_url or None,
                }
                for item in order.items.all()
            ]
            for it in items:
                if not it.get("picture_url"):
                    it.pop("picture_url", None)
        expires = order.reservation_expires_at or (timezone.now() + timedelta(hours=1))
        payer = {"name": order.customer_name, "email": order.email}
        if order.cpf:
            payer["identification"] = {"type": "CPF", "number": "".join(c for c in order.cpf if c.isdigit())}
        data = {
            "items": items,
            "payer": payer,
            "external_reference": str(order.public_id),
            "back_urls": {"success": return_url, "failure": return_url, "pending": return_url},
            "statement_descriptor": "".join(ch for ch in _store_name() if ch.isalnum() or ch == " ")[:22] or None,
            "expires": True,
            "expiration_date_to": expires.isoformat(timespec="milliseconds"),
            "date_of_expiration": expires.isoformat(timespec="milliseconds"),
            "payment_methods": {"installments": settings.MERCADOPAGO_MAX_INSTALLMENTS},
            "metadata": {"order_number": order.number},
        }
        if order.shipping_cost > 0:
            data["shipments"] = {"cost": float(order.shipping_cost), "mode": "not_specified"}
        if is_https:
            data["auto_return"] = "approved"
            data["notification_url"] = site + reverse("payments:webhook")
        if not data["statement_descriptor"]:
            data.pop("statement_descriptor")
        return data

    def create_preference(self, order) -> dict:
        result = self.sdk.preference().create(self.build_preference(order))
        status = result.get("status")
        response = result.get("response") or {}
        if status not in (200, 201) or not response.get("id"):
            logger.error("Mercado Pago recusou a preferência (status %s)", status)
            raise GatewayError("Não foi possível iniciar o pagamento. Tente novamente em instantes.")
        url = response.get("init_point") if self.is_production else (
            response.get("sandbox_init_point") or response.get("init_point"))
        return {"id": response["id"], "url": url}

    def get_payment(self, payment_id: str) -> dict:
        result = self.sdk.payment().get(payment_id)
        if result.get("status") != 200:
            raise GatewayError(f"Pagamento {payment_id} não encontrado no Mercado Pago.")
        return result["response"]

    def search_by_reference(self, reference: str) -> list[dict]:
        result = self.sdk.payment().search({"external_reference": reference, "sort": "date_created",
                                             "criteria": "desc"})
        if result.get("status") != 200:
            raise GatewayError("Falha ao consultar pagamentos.")
        return (result.get("response") or {}).get("results", [])


def _store_name() -> str:
    from apps.content.models import BrandSettings

    try:
        return BrandSettings.load().store_name
    except Exception:  # noqa: BLE001
        return settings.STORE_NAME


_gateway_override = None


def get_gateway() -> MercadoPagoGateway:
    return _gateway_override or MercadoPagoGateway()


def set_gateway_for_tests(gateway):
    global _gateway_override
    _gateway_override = gateway


def verify_webhook_signature(*, secret: str, x_signature: str, x_request_id: str, data_id: str) -> bool:
    """
    Valida o cabeçalho `x-signature` do Mercado Pago.
    Manifesto: id:{data.id};request-id:{x-request-id};ts:{ts};  (HMAC-SHA256 com a assinatura secreta)
    """
    if not secret or not x_signature:
        return False
    parts = {}
    for chunk in x_signature.split(","):
        if "=" in chunk:
            key, value = chunk.split("=", 1)
            parts[key.strip()] = value.strip()
    ts, received = parts.get("ts"), parts.get("v1")
    if not ts or not received:
        return False
    if data_id and data_id.isalnum():
        data_id = data_id.lower()
    manifest = ""
    if data_id:
        manifest += f"id:{data_id};"
    if x_request_id:
        manifest += f"request-id:{x_request_id};"
    manifest += f"ts:{ts};"
    expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received)


def to_decimal(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001
        return Decimal("0.00")
