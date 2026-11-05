"""
Cotação de frete com adaptadores extensíveis.

Nenhuma cotação é inventada: só retornamos opções de métodos configurados no painel
(retirada, frete fixo regional) ou cotações reais da API do Melhor Envio.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from decimal import Decimal

import requests
from django.conf import settings
from django.core.cache import cache

from apps.core.utils import money, only_digits, uf_from_cep

from .models import ShippingMethod

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShippingOption:
    code: str
    name: str
    price: Decimal
    days_min: int | None
    days_max: int | None
    method_id: int
    carrier: str = ""
    instructions: str = ""

    @property
    def is_free(self):
        return self.price <= 0

    @property
    def eta(self):
        if self.days_max is None:
            return ""
        if self.days_min and self.days_min != self.days_max:
            return f"{self.days_min} a {self.days_max} dias úteis"
        return f"até {self.days_max} dias úteis"


@dataclass
class PackageItem:
    product_id: int
    quantity: int
    unit_price: Decimal
    weight_grams: int
    length_cm: int
    width_cm: int
    height_cm: int


class ShippingError(Exception):
    pass


def origin_cep() -> str:
    return only_digits(settings.STORE_ORIGIN_ZIPCODE)


def _matches_region(method: ShippingMethod, cep: str) -> bool:
    uf = uf_from_cep(cep)
    states = method.state_list
    if states and uf not in states:
        return False
    ranges = method.cep_range_list()
    if ranges:
        number = int(cep)
        return any(start <= number <= end for start, end in ranges)
    return True


class MelhorEnvioClient:
    def __init__(self, token: str | None = None, environment: str | None = None):
        self.token = token if token is not None else settings.MELHORENVIO_TOKEN
        env = (environment or settings.MELHORENVIO_ENVIRONMENT).lower()
        self.base_url = "https://www.melhorenvio.com.br" if env == "production" else "https://sandbox.melhorenvio.com.br"

    @property
    def configured(self) -> bool:
        return bool(self.token and origin_cep())

    def calculate(self, to_cep: str, items: list[PackageItem], services: str = "") -> list[dict]:
        payload = {
            "from": {"postal_code": origin_cep()},
            "to": {"postal_code": to_cep},
            "products": [
                {
                    "id": str(i.product_id),
                    "width": max(i.width_cm, 11),
                    "height": max(i.height_cm, 2),
                    "length": max(i.length_cm, 16),
                    "weight": round(max(i.weight_grams, 50) / 1000, 3),
                    "insurance_value": float(i.unit_price),
                    "quantity": i.quantity,
                }
                for i in items
            ],
        }
        if services:
            payload["services"] = services
        response = requests.post(
            f"{self.base_url}/api/v2/me/shipment/calculate",
            json=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": settings.MELHORENVIO_USER_AGENT,
            },
            timeout=12,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else [data]


def quote(cep: str, items: list[PackageItem], subtotal: Decimal, *, client: MelhorEnvioClient | None = None
          ) -> list[ShippingOption]:
    cep = only_digits(cep)
    if len(cep) != 8:
        raise ShippingError("Informe um CEP válido com 8 dígitos.")
    if not items:
        return []
    options: list[ShippingOption] = []
    for method in ShippingMethod.objects.filter(is_active=True):
        if method.kind == ShippingMethod.Kind.PICKUP:
            if _matches_region(method, cep):
                options.append(ShippingOption(
                    code=f"m{method.pk}", name=method.name, price=Decimal("0.00"),
                    days_min=method.days_min, days_max=method.days_max, method_id=method.pk,
                    instructions=method.instructions,
                ))
        elif method.kind == ShippingMethod.Kind.FIXED:
            if _matches_region(method, cep):
                price = money(method.price)
                if method.free_above is not None and subtotal >= method.free_above:
                    price = Decimal("0.00")
                options.append(ShippingOption(
                    code=f"m{method.pk}", name=method.name, price=price,
                    days_min=method.days_min, days_max=method.days_max, method_id=method.pk,
                ))
        elif method.kind == ShippingMethod.Kind.MELHOR_ENVIO:
            options.extend(_melhor_envio_options(method, cep, items, subtotal, client or MelhorEnvioClient()))
    options.sort(key=lambda o: (o.price, o.days_max or 99))
    return options


def _melhor_envio_options(method, cep, items, subtotal, client: MelhorEnvioClient) -> list[ShippingOption]:
    if not client.configured:
        return []
    key_src = f"{cep}|{method.pk}|{method.service_ids}|" + "|".join(
        f"{i.product_id}:{i.quantity}:{i.weight_grams}" for i in items)
    cache_key = "me-quote:" + hashlib.sha256(key_src.encode()).hexdigest()
    results = cache.get(cache_key)
    if results is None:
        try:
            results = client.calculate(cep, items, method.service_ids.replace(" ", ""))
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Falha na cotação Melhor Envio: %s", exc.__class__.__name__)
            return []
        cache.set(cache_key, results, 600)
    options = []
    for r in results:
        if r.get("error") or not r.get("price"):
            continue
        price = money(r.get("custom_price") or r.get("price"))
        if method.free_above is not None and subtotal >= method.free_above:
            price = Decimal("0.00")
        delivery = r.get("custom_delivery_range") or r.get("delivery_range") or {}
        days_max = (r.get("custom_delivery_time") or r.get("delivery_time") or delivery.get("max") or 0)
        company = (r.get("company") or {}).get("name", "")
        options.append(ShippingOption(
            code=f"me{method.pk}-{r.get('id')}",
            name=f"{company} {r.get('name', '')}".strip(),
            price=price,
            days_min=(delivery.get("min") or None) and int(delivery["min"]) + method.extra_days,
            days_max=int(days_max) + method.extra_days if days_max else None,
            method_id=method.pk,
            carrier=company,
        ))
    return options


def find_option(options: list[ShippingOption], code: str) -> ShippingOption | None:
    return next((o for o in options if o.code == code), None)


def package_items_from_lines(lines) -> list[PackageItem]:
    """Converte linhas de carrinho (com .variant.product) em itens de pacote."""
    items = []
    for line in lines:
        p = line.variant.product
        items.append(PackageItem(
            product_id=p.pk, quantity=line.quantity, unit_price=line.unit_price,
            weight_grams=p.weight_grams, length_cm=p.length_cm, width_cm=p.width_cm, height_cm=p.height_cm,
        ))
    return items
