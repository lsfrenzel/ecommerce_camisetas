"""
Regras de estoque.

Todas as operações que alteram estoque travam as linhas de `ProductVariant` com
`select_for_update()` dentro de uma transação. A ordem de travamento é sempre por
`id` crescente, evitando deadlocks entre pedidos concorrentes. As constraints do
banco (`stock >= 0`, `reserved <= stock`) são a última linha de defesa.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import ProductVariant
from apps.core.audit import log_action
from apps.core.models import AuditLog

from .models import InventoryMovement, InventoryReservation


class InsufficientStock(Exception):
    def __init__(self, variant, requested, available):
        self.variant = variant
        self.requested = requested
        self.available = available
        super().__init__(
            f"Estoque insuficiente para {variant}: solicitado {requested}, disponível {available}."
        )


class InventoryError(Exception):
    pass


def lock_variants(variant_ids) -> dict[int, ProductVariant]:
    """Trava as variações (ordem determinística) e devolve {id: variant}."""
    ids = sorted(set(variant_ids))
    locked = (
        ProductVariant.objects.select_for_update(of=("self",))
        .select_related("product", "color", "size")
        .filter(pk__in=ids)
        .order_by("pk")
    )
    return {v.pk: v for v in locked}


def reserve_for_order(order, quantities: dict[int, int], variants: dict[int, ProductVariant] | None = None):
    """Reserva estoque para um pedido. Deve ser chamado dentro de transaction.atomic()."""
    if variants is None:
        variants = lock_variants(quantities.keys())
    expires_at = timezone.now() + timedelta(minutes=settings.STOCK_RESERVATION_MINUTES)
    for variant_id, qty in quantities.items():
        variant = variants[variant_id]
        if variant.available < qty:
            raise InsufficientStock(variant, qty, variant.available)
        variant.reserved += qty
        variant.save(update_fields=["reserved", "updated_at"])
        InventoryReservation.objects.create(variant=variant, order=order, quantity=qty, expires_at=expires_at)
    return expires_at


@transaction.atomic
def release_reservations(order, reason: str = "") -> int:
    """Libera reservas ativas de um pedido (cancelamento ou expiração)."""
    reservations = list(
        InventoryReservation.objects.select_for_update().filter(order=order, status=InventoryReservation.Status.ACTIVE)
    )
    if not reservations:
        return 0
    variants = lock_variants([r.variant_id for r in reservations])
    for r in reservations:
        v = variants[r.variant_id]
        v.reserved = max(v.reserved - r.quantity, 0)
        v.save(update_fields=["reserved", "updated_at"])
        r.status = InventoryReservation.Status.RELEASED
        r.save(update_fields=["status", "updated_at"])
    return len(reservations)


@transaction.atomic
def consume_for_paid_order(order) -> list[str]:
    """
    Converte reservas em baixa definitiva de estoque após pagamento aprovado.

    Se a reserva já expirou (pagamento tardio), tenta baixar o estoque disponível.
    Retorna avisos para itens que não puderam ser atendidos (pedido exige atenção).
    """
    warnings: list[str] = []
    reservations = list(
        InventoryReservation.objects.select_for_update().filter(order=order, status=InventoryReservation.Status.ACTIVE)
    )
    reserved_by_variant: dict[int, int] = defaultdict(int)
    for r in reservations:
        reserved_by_variant[r.variant_id] += r.quantity

    needed: dict[int, int] = defaultdict(int)
    for item in order.items.exclude(variant__isnull=True):
        needed[item.variant_id] += item.quantity

    variants = lock_variants(list(needed.keys()))
    for variant_id, qty in needed.items():
        v = variants[variant_id]
        from_reservation = min(reserved_by_variant.get(variant_id, 0), qty)
        extra = qty - from_reservation
        if extra > v.available:
            warnings.append(f"{v.sku}: faltam {extra - v.available} unidade(s) em estoque")
            extra = v.available
        take = from_reservation + extra
        if take <= 0:
            continue
        v.reserved -= from_reservation
        v.stock -= take
        v.save(update_fields=["stock", "reserved", "updated_at"])
        InventoryMovement.objects.create(
            variant=v, kind=InventoryMovement.Kind.SALE, quantity=-take, stock_after=v.stock,
            reason=f"Pedido {order.number}", order=order,
        )
    for r in reservations:
        r.status = InventoryReservation.Status.CONSUMED
        r.save(update_fields=["status", "updated_at"])
    return warnings


@transaction.atomic
def restock_order(order, user=None, reason="Cancelamento / devolução"):
    """Devolve ao estoque as unidades baixadas por um pedido pago."""
    sold: dict[int, int] = defaultdict(int)
    for m in InventoryMovement.objects.filter(
        order=order, kind__in=[InventoryMovement.Kind.SALE, InventoryMovement.Kind.RETURN]
    ):
        sold[m.variant_id] -= m.quantity
    to_return = {vid: qty for vid, qty in sold.items() if qty > 0}
    if not to_return:
        return 0
    variants = lock_variants(to_return.keys())
    for vid, qty in to_return.items():
        v = variants[vid]
        v.stock += qty
        v.save(update_fields=["stock", "updated_at"])
        InventoryMovement.objects.create(
            variant=v, kind=InventoryMovement.Kind.RETURN, quantity=qty, stock_after=v.stock,
            reason=f"{reason} · pedido {order.number}", order=order, user=user,
        )
    return sum(to_return.values())


@transaction.atomic
def record_movement(variant_id: int, kind: str, quantity: int, *, user=None, reason="", unit_cost=None,
                    request=None) -> InventoryMovement:
    """Movimentação manual (entrada, saída, ajuste, perda) feita pela equipe."""
    if quantity == 0:
        raise InventoryError("A quantidade não pode ser zero.")
    v = lock_variants([variant_id])[variant_id]
    if kind in (InventoryMovement.Kind.EXIT, InventoryMovement.Kind.LOSS) and quantity > 0:
        quantity = -quantity
    if kind == InventoryMovement.Kind.ENTRY and quantity < 0:
        raise InventoryError("Entradas devem ter quantidade positiva.")
    new_stock = v.stock + quantity
    if new_stock < 0:
        raise InventoryError(f"Operação deixaria o estoque negativo ({new_stock}).")
    if new_stock < v.reserved:
        raise InventoryError(
            f"Há {v.reserved} unidade(s) reservada(s) para pedidos pendentes; o estoque não pode ficar abaixo disso."
        )
    before = v.stock
    v.stock = new_stock
    v.save(update_fields=["stock", "updated_at"])
    movement = InventoryMovement.objects.create(
        variant=v, kind=kind, quantity=quantity, stock_after=v.stock, reason=reason, user=user, unit_cost=unit_cost,
    )
    log_action(actor=user, action=AuditLog.Action.STOCK_MOVEMENT, obj=v, request=request,
               changes={"stock": [before, v.stock]}, message=f"{movement.get_kind_display()}: {reason}"[:255])
    return movement


@transaction.atomic
def set_stock(variant_id: int, new_stock: int, *, user=None, reason="Ajuste de inventário", request=None):
    v = ProductVariant.objects.get(pk=variant_id)
    delta = new_stock - v.stock
    if delta == 0:
        return None
    return record_movement(variant_id, InventoryMovement.Kind.ADJUSTMENT, delta, user=user, reason=reason,
                           request=request)


def release_expired_reservations(now=None) -> int:
    """Cancela pedidos não pagos com reserva expirada e libera o estoque."""
    from apps.orders.models import Order
    from apps.orders.services import expire_order

    now = now or timezone.now()
    order_ids = (
        InventoryReservation.objects.filter(status=InventoryReservation.Status.ACTIVE, expires_at__lt=now)
        .values_list("order_id", flat=True).distinct()
    )
    count = 0
    for order in Order.objects.filter(pk__in=list(order_ids)):
        if expire_order(order):
            count += 1
    return count
