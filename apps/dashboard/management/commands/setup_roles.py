from django.core.management.base import BaseCommand

from apps.dashboard.forms import ensure_groups


class Command(BaseCommand):
    help = "Cria/atualiza os papéis da equipe (Administrador geral, Gestor comercial, Estoquista, Atendimento)."

    def handle(self, *args, **options):
        ensure_groups()
        self.stdout.write(self.style.SUCCESS("Papéis atualizados."))
