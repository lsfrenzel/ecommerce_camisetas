import os
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.accounts.models import User


def run(**env):
    out = StringIO()
    with mock.patch.dict(os.environ, env, clear=False):
        for key in ("DJANGO_SUPERUSER_EMAIL", "DJANGO_SUPERUSER_PASSWORD", "DJANGO_SUPERUSER_FULL_NAME"):
            if key not in env:
                os.environ.pop(key, None)
        call_command("ensure_superuser", stdout=out)
    return out.getvalue()


class EnsureSuperuserTests(TestCase):
    def test_noop_without_variables(self):
        output = run()
        self.assertIn("nada a fazer", output)
        self.assertFalse(User.objects.exists())

    def test_creates_superuser_with_staff_access(self):
        output = run(DJANGO_SUPERUSER_EMAIL="Dono@Loja.com", DJANGO_SUPERUSER_PASSWORD="Quebrada-Admin-2026!",
                     DJANGO_SUPERUSER_FULL_NAME="Dono da Loja")
        user = User.objects.get(email="dono@loja.com")
        self.assertTrue(user.is_superuser and user.is_staff and user.is_active)
        self.assertEqual(user.full_name, "Dono da Loja")
        self.assertTrue(user.check_password("Quebrada-Admin-2026!"))
        self.assertNotIn("Quebrada-Admin-2026!", output, "a senha nunca aparece no log")
        self.client.force_login(user)
        self.assertEqual(self.client.get("/painel/").status_code, 200)

    def test_existing_user_is_not_changed(self):
        User.objects.create_superuser(email="dono@loja.com", password="Senha-Trocada-Depois-1", full_name="Dono")
        output = run(DJANGO_SUPERUSER_EMAIL="dono@loja.com", DJANGO_SUPERUSER_PASSWORD="Outra-Senha-Forte-2")
        self.assertIn("já existe", output)
        self.assertTrue(User.objects.get(email="dono@loja.com").check_password("Senha-Trocada-Depois-1"))

    def test_weak_password_rejected(self):
        with self.assertRaises(CommandError):
            run(DJANGO_SUPERUSER_EMAIL="dono@loja.com", DJANGO_SUPERUSER_PASSWORD="123")
        self.assertFalse(User.objects.exists())
