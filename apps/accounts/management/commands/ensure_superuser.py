"""
Cria o primeiro superusuário a partir de variáveis de ambiente (útil no Railway, sem terminal).

Variáveis:
  DJANGO_SUPERUSER_EMAIL      e-mail de acesso (obrigatória para o comando agir)
  DJANGO_SUPERUSER_PASSWORD   senha inicial (obrigatória para o comando agir)
  DJANGO_SUPERUSER_FULL_NAME  nome exibido (opcional, padrão "Administrador")

Comportamento:
- Sem as duas variáveis obrigatórias: não faz nada.
- Se já existir um usuário com o e-mail: não altera nada (nem a senha), para não sobrescrever
  uma senha trocada depois pelo próprio administrador.
- A senha passa pelos validadores do Django; a senha nunca é exibida nos logs.
"""

import os

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Cria o superusuário definido por DJANGO_SUPERUSER_EMAIL/PASSWORD, se ainda não existir."

    def handle(self, *args, **options):
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip().lower()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        full_name = os.environ.get("DJANGO_SUPERUSER_FULL_NAME", "").strip() or "Administrador"

        if not email or not password:
            self.stdout.write("ensure_superuser: DJANGO_SUPERUSER_EMAIL/PASSWORD não definidas — nada a fazer.")
            return

        User = get_user_model()
        if User.objects.filter(email__iexact=email).exists():
            self.stdout.write(f"ensure_superuser: usuário {email} já existe — nenhuma alteração feita.")
            return

        candidate = User(email=email, full_name=full_name)
        try:
            password_validation.validate_password(password, candidate)
        except ValidationError as exc:
            raise CommandError(
                "ensure_superuser: senha de DJANGO_SUPERUSER_PASSWORD recusada: " + " ".join(exc.messages)
            ) from exc

        User.objects.create_superuser(email=email, password=password, full_name=full_name)
        self.stdout.write(self.style.SUCCESS(
            f"ensure_superuser: superusuário {email} criado. Remova DJANGO_SUPERUSER_PASSWORD das variáveis após o primeiro acesso."
        ))
