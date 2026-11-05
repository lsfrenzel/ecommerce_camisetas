import json
import re

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.orders.models import Order

from . import factories as f


class SignupLoginTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_signup_creates_user_profile_and_logs_in(self):
        resp = self.client.post(reverse("accounts:signup"), {
            "full_name": "Ana Souza", "email": "Ana@Exemplo.com", "password1": "Quebrada-2026!x",
            "password2": "Quebrada-2026!x", "accept_terms": "on",
        })
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(email="ana@exemplo.com")
        self.assertFalse(user.profile.marketing_opt_in, "consentimento de marketing nunca é pré-marcado")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_signup_requires_terms_and_valid_password(self):
        resp = self.client.post(reverse("accounts:signup"), {
            "full_name": "Ana", "email": "ana@exemplo.com", "password1": "123", "password2": "123"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(email="ana@exemplo.com").exists())
        self.assertIn("accept_terms", resp.context["form"].errors)
        self.assertIn("password1", resp.context["form"].errors)

    def test_signup_rejects_duplicate_email_case_insensitive(self):
        f.user(email="dup@exemplo.com")
        resp = self.client.post(reverse("accounts:signup"), {
            "full_name": "X", "email": "DUP@exemplo.com", "password1": "Quebrada-2026!x",
            "password2": "Quebrada-2026!x", "accept_terms": "on"})
        self.assertIn("email", resp.context["form"].errors)

    def test_login_with_email_case_insensitive(self):
        f.user(email="joao@exemplo.com", password="Senha-Forte-123")
        resp = self.client.post(reverse("accounts:login"), {"email": "JOAO@exemplo.com", "password": "Senha-Forte-123"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_login_wrong_password(self):
        f.user(email="joao@exemplo.com")
        resp = self.client.post(reverse("accounts:login"), {"email": "joao@exemplo.com", "password": "errada"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(LOGIN_RATE_LIMIT_ATTEMPTS=3)
    def test_login_rate_limit_blocks_even_correct_password(self):
        f.user(email="alvo@exemplo.com", password="Senha-Forte-123")
        for _ in range(3):
            self.client.post(reverse("accounts:login"), {"email": "alvo@exemplo.com", "password": "errada"})
        resp = self.client.post(reverse("accounts:login"), {"email": "alvo@exemplo.com", "password": "Senha-Forte-123"})
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(resp, "Muitas tentativas")

    def test_blocked_user_cannot_login(self):
        f.user(email="bloq@exemplo.com", is_active=False)
        self.client.post(reverse("accounts:login"), {"email": "bloq@exemplo.com", "password": "Senha-Forte-123"})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_open_redirect_is_blocked(self):
        f.user(email="r@exemplo.com")
        resp = self.client.post(reverse("accounts:login") , {"email": "r@exemplo.com", "password": "Senha-Forte-123",
                                                             "next": "https://malicioso.com/"})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(resp.url.startswith("https://malicioso.com"))


class PasswordResetTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_full_password_reset_flow(self):
        f.user(email="esqueci@exemplo.com", password="Antiga-Senha-1")
        resp = self.client.post(reverse("accounts:password_reset"), {"email": "esqueci@exemplo.com"})
        self.assertRedirects(resp, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        match = re.search(r"/conta/senha/redefinir/[^/\s]+/[^/\s]+/", mail.outbox[0].body)
        self.assertIsNotNone(match, mail.outbox[0].body)
        resp = self.client.get(match.group(0), follow=True)
        self.assertEqual(resp.status_code, 200)
        post_url = resp.redirect_chain[-1][0]
        resp = self.client.post(post_url, {"new_password1": "Nova-Senha-Forte-9", "new_password2": "Nova-Senha-Forte-9"})
        self.assertRedirects(resp, reverse("accounts:password_reset_complete"))
        self.assertTrue(User.objects.get(email="esqueci@exemplo.com").check_password("Nova-Senha-Forte-9"))

    def test_unknown_email_does_not_leak(self):
        resp = self.client.post(reverse("accounts:password_reset"), {"email": "ninguem@exemplo.com"})
        self.assertRedirects(resp, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)


class AccountAreaTests(TestCase):
    def test_account_requires_login(self):
        resp = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp.url)

    def test_address_of_other_user_is_404(self):
        owner, intruder = f.user(), f.user()
        from apps.accounts.models import Address

        addr = Address.objects.create(user=owner, recipient_name="X", cep="01001-000", street="Rua", number="1",
                                      neighborhood="Centro", city="SP", state="SP")
        self.client.force_login(intruder)
        self.assertEqual(self.client.get(reverse("accounts:address_edit", args=[addr.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("accounts:address_delete", args=[addr.pk])).status_code, 404)

    def test_data_export_contains_only_own_data(self):
        u = f.user(email="dono@exemplo.com")
        self.client.force_login(u)
        resp = self.client.get(reverse("accounts:export_data"))
        data = json.loads(resp.content)
        self.assertEqual(data["conta"]["email"], "dono@exemplo.com")

    def test_signup_claims_only_guest_orders_from_same_session(self):
        cache.clear()
        stranger_order = Order.objects.create(email="novo@exemplo.com", customer_name="X", phone="1", ship_recipient="X",
                                              ship_cep="01001-000", ship_street="R", ship_number="1", ship_neighborhood="B",
                                              ship_city="C", ship_state="SP", shipping_name="F", subtotal=10, total=10)
        session_order = Order.objects.create(email="novo@exemplo.com", customer_name="X", phone="1", ship_recipient="X",
                                             ship_cep="01001-000", ship_street="R", ship_number="1", ship_neighborhood="B",
                                             ship_city="C", ship_state="SP", shipping_name="F", subtotal=10, total=10)
        session = self.client.session
        session["guest_orders"] = [str(session_order.public_id)]
        session.save()
        self.client.post(reverse("accounts:signup"), {
            "full_name": "Novo", "email": "novo@exemplo.com", "password1": "Quebrada-2026!x",
            "password2": "Quebrada-2026!x", "accept_terms": "on"})
        user = User.objects.get(email="novo@exemplo.com")
        session_order.refresh_from_db()
        stranger_order.refresh_from_db()
        self.assertEqual(session_order.user, user)
        self.assertIsNone(stranger_order.user, "pedidos de outra sessão não podem ser vinculados só pelo e-mail")
