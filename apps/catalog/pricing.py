"""
Motor de preços.

O preço final de uma variação é o MENOR entre:
- preço base (preço específico da variação ou preço do produto);
- preço promocional do produto, se vigente;
- preço resultante de cada promoção automática vigente aplicável.

Promoções não são cumulativas entre si; a melhor para o cliente vence.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone

from apps.core.utils import money


@dataclass(frozen=True)
class PriceInfo:
    base: Decimal
    final: Decimal
    label: str = ""

    @property
    def on_sale(self) -> bool:
        return self.final < self.base

    @property
    def discount(self) -> Decimal:
        return self.base - self.final

    @property
    def percent_off(self) -> int:
        if not self.on_sale or not self.base:
            return 0
        return int(round((1 - self.final / self.base) * 100))


class PricingEngine:
    def __init__(self, now=None):
        from apps.promotions.models import Promotion

        self.now = now or timezone.now()
        self.promotions = []
        for promo in Promotion.live(self.now).prefetch_related("products", "categories", "collections"):
            self.promotions.append(
                (
                    promo,
                    {p.pk for p in promo.products.all()},
                    {c.pk for c in promo.categories.all()},
                    {c.pk for c in promo.collections.all()},
                )
            )

    def _collection_ids(self, product) -> set[int]:
        cache = getattr(product, "_collection_ids", None)
        if cache is None:
            cache = {c.pk for c in product.collections.all()}
            product._collection_ids = cache
        return cache

    def applicable_promotions(self, product):
        for promo, product_ids, category_ids, collection_ids in self.promotions:
            if (
                promo.applies_to_all
                or product.pk in product_ids
                or product.category_id in category_ids
                or (collection_ids and self._collection_ids(product) & collection_ids)
            ):
                yield promo

    def price_for(self, product, variant=None) -> PriceInfo:
        base = money(variant.base_price if variant is not None else product.price)
        best = base
        label = ""
        if product.sale_is_active(self.now):
            # Para variações com preço específico, o desconto do produto é aplicado proporcionalmente.
            ratio = product.sale_price / product.price if product.price else Decimal("1")
            candidate = money(base * ratio)
            if candidate < best:
                best, label = candidate, "Oferta"
        for promo in self.applicable_promotions(product):
            if promo.kind == "percent":
                candidate = money(base * (Decimal("100") - promo.value) / Decimal("100"))
            else:
                candidate = money(base - promo.value)
            candidate = max(candidate, Decimal("0.00"))
            if candidate < best:
                best, label = candidate, promo.label or promo.name
        return PriceInfo(base=base, final=best, label=label)

    def annotate(self, products):
        """Anexa `price_info` aos produtos (para listagens)."""
        for product in products:
            product.price_info = self.price_for(product)
        return products


def installments_text(value: Decimal, brand) -> str:
    """Texto de parcelamento informativo (as condições reais são definidas no Mercado Pago)."""
    max_n = int(brand.max_installments_display or 1)
    min_value = brand.min_installment_value or Decimal("1")
    n = max_n
    while n > 1 and value / n < min_value:
        n -= 1
    if n <= 1:
        return ""
    from apps.core.utils import format_brl

    return f"ou {n}x de {format_brl(money(value / n))} sem juros"
