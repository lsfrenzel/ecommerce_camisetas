from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.orders.models import Order, OrderStatus, PaymentStatus
from apps.payments.gateway import GatewayError
from apps.payments.services import reconcile_order


class Command(BaseCommand):
    help = "Consulta no Mercado Pago os pedidos recentes ainda não confirmados (reconciliação)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=3)

    def handle(self, *args, **options):
        if not settings.MERCADOPAGO_ACCESS_TOKEN:
            raise CommandError("MERCADOPAGO_ACCESS_TOKEN não configurado.")
        since = timezone.now() - timedelta(days=options["days"])
        qs = Order.objects.filter(created_at__gte=since).filter(
            status__in=[OrderStatus.AWAITING_PAYMENT, OrderStatus.CANCELLED],
        ).exclude(payment_status=PaymentStatus.APPROVED)
        changed = 0
        for order in qs:
            before = order.payment_status
            try:
                reconcile_order(order)
            except GatewayError as exc:
                self.stderr.write(f"{order.number}: {exc}")
                continue
            if order.payment_status != before:
                changed += 1
        self.stdout.write(self.style.SUCCESS(f"{qs.count()} pedido(s) verificados, {changed} atualizado(s)."))
