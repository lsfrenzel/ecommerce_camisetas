"""
Métricas comerciais calculadas diretamente no banco (PostgreSQL).

Definições usadas no painel:
- Faturamento bruto: soma do total (produtos + frete − descontos) dos pedidos REALIZADOS no período,
  exceto cancelados. Inclui pedidos ainda aguardando pagamento.
- Receita: soma do total dos pedidos PAGOS no período (data do pagamento), exceto reembolsados.
- Receita de produtos: receita − frete.
- CMV (custo dos produtos vendidos): Σ custo unitário registrado no momento da venda × quantidade.
- Lucro bruto estimado: receita de produtos − CMV − tarifas do gateway conhecidas.
  NÃO é lucro líquido: não considera impostos, embalagem, marketing, folha e demais despesas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from apps.catalog.models import Product, ProductVariant
from apps.orders.models import PAID_STATUSES, Order, OrderItem, OrderStatus
from apps.payments.models import Payment

ZERO = Decimal("0.00")
MONEY = DecimalField(max_digits=14, decimal_places=2)

PERIODS = {
    "hoje": "Hoje",
    "7d": "Últimos 7 dias",
    "30d": "Últimos 30 dias",
    "personalizado": "Personalizado",
}


@dataclass
class Period:
    key: str
    start: datetime
    end: datetime

    @property
    def label(self):
        if self.key == "personalizado":
            return f"{timezone.localtime(self.start):%d/%m/%Y} a {timezone.localtime(self.end):%d/%m/%Y}"
        return PERIODS.get(self.key, "")


def resolve_period(params) -> Period:
    key = params.get("periodo", "30d")
    tz = timezone.get_current_timezone()
    today = timezone.localdate()
    if key == "hoje":
        start_d, end_d = today, today
    elif key == "7d":
        start_d, end_d = today - timedelta(days=6), today
    elif key == "personalizado":
        try:
            start_d = date.fromisoformat(params.get("inicio", ""))
            end_d = date.fromisoformat(params.get("fim", ""))
            if end_d < start_d:
                start_d, end_d = end_d, start_d
            if (end_d - start_d).days > 731:
                start_d = end_d - timedelta(days=731)
        except ValueError:
            key, start_d, end_d = "30d", today - timedelta(days=29), today
    else:
        key, start_d, end_d = "30d", today - timedelta(days=29), today
    start = timezone.make_aware(datetime.combine(start_d, time.min), tz)
    end = timezone.make_aware(datetime.combine(end_d, time.max), tz)
    return Period(key=key, start=start, end=end)


def paid_orders(period: Period):
    return Order.objects.filter(paid_at__range=(period.start, period.end), status__in=PAID_STATUSES)


def overview(period: Period) -> dict:
    placed = Order.objects.filter(created_at__range=(period.start, period.end)).exclude(status=OrderStatus.CANCELLED)
    paid = paid_orders(period)
    gross = placed.aggregate(v=Coalesce(Sum("total"), ZERO, output_field=MONEY))["v"]
    agg = paid.aggregate(
        revenue=Coalesce(Sum("total"), ZERO, output_field=MONEY),
        shipping=Coalesce(Sum("shipping_cost"), ZERO, output_field=MONEY),
        promo=Coalesce(Sum("promotion_discount"), ZERO, output_field=MONEY),
        coupon=Coalesce(Sum("coupon_discount"), ZERO, output_field=MONEY),
        count=Count("id"),
    )
    cost = OrderItem.objects.filter(order__in=paid).aggregate(
        v=Coalesce(Sum(ExpressionWrapper(F("unit_cost") * F("quantity"), output_field=MONEY)), ZERO,
                   output_field=MONEY))["v"]
    fees = Payment.objects.filter(order__in=paid, fee_amount__isnull=False).aggregate(
        v=Coalesce(Sum("fee_amount"), ZERO, output_field=MONEY))["v"]
    product_revenue = agg["revenue"] - agg["shipping"]
    count = agg["count"]
    return {
        "gross": gross,
        "revenue": agg["revenue"],
        "product_revenue": product_revenue,
        "shipping": agg["shipping"],
        "paid_count": count,
        "placed_count": placed.count(),
        "avg_ticket": (agg["revenue"] / count).quantize(Decimal("0.01")) if count else ZERO,
        "discounts": agg["promo"] + agg["coupon"],
        "promo_discounts": agg["promo"],
        "coupon_discounts": agg["coupon"],
        "cogs": cost,
        "gateway_fees": fees,
        "gross_profit": product_revenue - cost - fees,
    }


def status_counts() -> dict:
    """Situação atual (independe do período)."""
    counts = dict(Order.objects.values_list("status").annotate(c=Count("id")).values_list("status", "c"))
    return {
        "awaiting": counts.get(OrderStatus.AWAITING_PAYMENT, 0),
        "paid": counts.get(OrderStatus.PAID, 0),
        "production": counts.get(OrderStatus.IN_PRODUCTION, 0) + counts.get(OrderStatus.CUSTOMIZING, 0),
        "ready": counts.get(OrderStatus.READY_TO_SHIP, 0),
        "shipped": counts.get(OrderStatus.SHIPPED, 0),
        "delivered": counts.get(OrderStatus.DELIVERED, 0),
        "attention": Order.objects.filter(needs_attention=True).count(),
    }


def daily_series(period: Period) -> dict:
    rows = (
        paid_orders(period).annotate(day=TruncDate("paid_at", tzinfo=timezone.get_current_timezone()))
        .values("day").annotate(total=Sum("total"), count=Count("id")).order_by("day")
    )
    by_day = {r["day"]: r for r in rows}
    labels, totals, counts = [], [], []
    day = timezone.localtime(period.start).date()
    last = timezone.localtime(period.end).date()
    while day <= last:
        r = by_day.get(day)
        labels.append(day.strftime("%d/%m"))
        totals.append(float(r["total"]) if r else 0.0)
        counts.append(r["count"] if r else 0)
        day += timedelta(days=1)
    return {"labels": labels, "totals": totals, "counts": counts}


def top_products(period: Period, limit=10):
    return list(
        OrderItem.objects.filter(order__in=paid_orders(period))
        .values("product_name")
        .annotate(units=Sum("quantity"), revenue=Sum("line_total"))
        .order_by("-units")[:limit]
    )


def low_stock(limit=20):
    return list(
        ProductVariant.objects.filter(is_active=True, product__status=Product.Status.ACTIVE)
        .annotate(avail=F("stock") - F("reserved"))
        .filter(avail__lte=F("low_stock_threshold"))
        .select_related("product", "color", "size").order_by("avail")[:limit]
    )


def breakdown(period: Period, field: str):
    """Vendas agrupadas por campo do item (category_name, size_name, color_name)."""
    return list(
        OrderItem.objects.filter(order__in=paid_orders(period))
        .values(field).annotate(units=Sum("quantity"), revenue=Sum("line_total")).order_by("-revenue")
    )


def coupons_used(period: Period):
    return list(
        paid_orders(period).exclude(coupon_code="").values("coupon_code")
        .annotate(uses=Count("id"), discount=Sum("coupon_discount"), revenue=Sum("total")).order_by("-uses")
    )


def cancelled_orders(period: Period):
    return Order.objects.filter(
        Q(cancelled_at__range=(period.start, period.end)) | Q(status=OrderStatus.REFUNDED, updated_at__range=(period.start, period.end))
    ).order_by("-updated_at")


def stale_products(days=60):
    """Produtos ativos com estoque e sem vendas nos últimos N dias (sem giro)."""
    since = timezone.now() - timedelta(days=days)
    sold_ids = OrderItem.objects.filter(order__paid_at__gte=since).values_list("product_id", flat=True)
    return (
        Product.objects.visible().exclude(pk__in=sold_ids)
        .annotate(stock_total=Coalesce(Sum("variants__stock"), 0)).filter(stock_total__gt=0).order_by("-stock_total")
    )
