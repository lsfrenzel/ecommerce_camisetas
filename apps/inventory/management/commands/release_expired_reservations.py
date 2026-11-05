from django.core.management.base import BaseCommand

from apps.inventory.services import release_expired_reservations


class Command(BaseCommand):
    help = "Cancela pedidos não pagos com reserva expirada e devolve o estoque reservado. Agende (cron) a cada 10-15 min."

    def handle(self, *args, **options):
        count = release_expired_reservations()
        self.stdout.write(self.style.SUCCESS(f"{count} pedido(s) expirado(s) liberado(s)."))
