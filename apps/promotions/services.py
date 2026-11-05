"""Validação e cálculo de cupons."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone

from apps.core.utils import money

from .models import Coupon


class CouponError(Exception):
    pass


@dataclass
class PricedLine:
    product_id: int
    category_id: int
    unit_price: Decimal          # preço final unitário (após promoções)
    original_unit_price: Decimal  # preço base
    quantity: int
    extra_fee: Decimal = Decimal("0")  # personalização (não recebe desconto de cupom)

    @property
    def on_promotion(self) -> bool:
        return self.unit_price < self.original_unit_price

    @property
    def total(self) -> Decimal:
        return self.unit_price * self.quantity


@dataclass
class CouponResult:
    coupon: Coupon
    discount: Decimal
    free_shipping: bool = False


def evaluate_coupon(coupon: Coupon | None, lines: list[PricedLine], *, user=None, email: str = "",
                    now=None) -> CouponResult:
    """Valida o cupom para o carrinho e retorna o desconto. Lança CouponError com mensagem amigável."""
    if coupon is None:
        raise CouponError("Cupom não encontrado.")
    now = now or timezone.now()
    if not coupon.is_active:
        raise CouponError("Este cupom não está ativo.")
    if coupon.starts_at and now < coupon.starts_at:
        raise CouponError("Este cupom ainda não está válido.")
    if coupon.ends_at and now > coupon.ends_at:
        raise CouponError("Este cupom expirou.")

    subtotal = sum((l.total for l in lines), Decimal("0"))
    if subtotal < coupon.min_order_value:
        from apps.core.utils import format_brl

        raise CouponError(f"Pedido mínimo para este cupom: {format_brl(coupon.min_order_value)}.")

    if coupon.max_uses is not None and coupon.uses_count() >= coupon.max_uses:
        raise CouponError("Este cupom atingiu o limite de utilizações.")

    email = (email or (user.email if user and user.is_authenticated else "")).lower()
    if coupon.max_uses_per_customer is not None and (email or (user and user.is_authenticated)):
        from django.db.models import Q

        q = Q(email__iexact=email) if email else Q()
        if user is not None and user.is_authenticated:
            q |= Q(user=user)
        used = coupon.redemptions.exclude(order__status="cancelled").filter(q).count()
        if used >= coupon.max_uses_per_customer:
            raise CouponError("Você já utilizou este cupom.")

    if coupon.first_order_only and user is not None and user.is_authenticated:
        from apps.orders.models import PAID_STATUSES

        if user.orders.filter(status__in=PAID_STATUSES).exists():
            raise CouponError("Este cupom é válido somente para a primeira compra.")

    product_ids = set(coupon.products.values_list("pk", flat=True))
    category_ids = set(coupon.categories.values_list("pk", flat=True))
    eligible = []
    for line in lines:
        if product_ids or category_ids:
            if line.product_id not in product_ids and line.category_id not in category_ids:
                continue
        if not coupon.stackable_with_promotions and line.on_promotion:
            continue
        eligible.append(line)
    base = sum((l.total for l in eligible), Decimal("0"))

    if coupon.kind == Coupon.Kind.FREE_SHIPPING:
        return CouponResult(coupon=coupon, discount=Decimal("0.00"), free_shipping=True)

    if base <= 0:
        raise CouponError(
            "Este cupom não é cumulativo com produtos em promoção."
            if not coupon.stackable_with_promotions else "Nenhum item do carrinho é elegível para este cupom."
        )

    if coupon.kind == Coupon.Kind.PERCENT:
        discount = money(base * coupon.value / Decimal("100"))
        if coupon.max_discount is not None:
            discount = min(discount, coupon.max_discount)
    else:
        discount = min(money(coupon.value), base)
    return CouponResult(coupon=coupon, discount=money(discount))


def find_coupon(code: str) -> Coupon | None:
    code = (code or "").strip().upper()
    if not code:
        return None
    return Coupon.objects.filter(code=code).first()
