from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.core.models import AuditLog

from . import factories as f


class UserManagementTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = f.staff("Administrador geral")
        self.client.force_login(self.admin)

    def test_list_filters(self):
        f.user(email="cli@exemplo.com")
        f.user(email="bloq@exemplo.com", is_active=False)
        url = reverse("dashboard:customers")
        emails = lambda r: [u.email for u, _ in r.context["rows"]]  # noqa: E731
        self.assertEqual(emails(self.client.get(url)), ["cli@exemplo.com"])
        self.assertIn(self.admin.email, emails(self.client.get(url, {"tipo": "equipe"})))
        self.assertEqual(emails(self.client.get(url, {"tipo": "bloqueados"})), ["bloq@exemplo.com"])
        self.assertEqual(len(emails(self.client.get(url, {"tipo": "todos"}))), 3)

    def test_create_user_sends_password_link_and_staff_never_knows_password(self):
        resp = self.client.post(reverse("dashboard:user_new"), {
            "full_name": "Cliente Balcão", "email": "Balcao@Exemplo.com", "phone": "11988887777", "send_link": "1"})
        user = User.objects.get(email="balcao@exemplo.com")
        self.assertRedirects(resp, reverse("dashboard:customer_detail", args=[user.pk]))
        self.assertFalse(user.is_staff)
        self.assertTrue(user.has_usable_password())
        self.assertEqual(user.profile.phone, "11988887777")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/conta/senha/redefinir/", mail.outbox[0].body)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.CREATE, object_id=str(user.pk)).exists())

    def test_create_user_rejects_duplicate_email(self):
        f.user(email="existe@exemplo.com")
        resp = self.client.post(reverse("dashboard:user_new"), {"full_name": "X", "email": "EXISTE@exemplo.com"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(User.objects.filter(email__iexact="existe@exemplo.com").count(), 1)

    def test_edit_user_data_audited_with_cpf_masked(self):
        customer = f.user(email="velho@exemplo.com")
        self.client.post(reverse("dashboard:customer_detail", args=[customer.pk]), {
            "action": "edit", "full_name": "Nome Novo", "email": "novo@exemplo.com", "phone": "",
            "cpf": "529.982.247-25", "birth_date": ""})
        customer.refresh_from_db()
        self.assertEqual((customer.full_name, customer.email, customer.profile.cpf),
                         ("Nome Novo", "novo@exemplo.com", "52998224725"))
        log = AuditLog.objects.filter(action=AuditLog.Action.UPDATE, object_id=str(customer.pk)).latest("created_at")
        self.assertEqual(log.changes["cpf"], ["***", "***"])
        self.assertNotIn("52998224725", str(log.changes))

    def test_edit_rejects_invalid_cpf_and_taken_email(self):
        f.user(email="ocupado@exemplo.com")
        customer = f.user(email="c@exemplo.com")
        resp = self.client.post(reverse("dashboard:customer_detail", args=[customer.pk]), {
            "action": "edit", "full_name": "C", "email": "ocupado@exemplo.com", "cpf": "111.111.111-11"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("email", resp.context["data_form"].errors)
        self.assertIn("cpf", resp.context["data_form"].errors)
        customer.refresh_from_db()
        self.assertEqual(customer.email, "c@exemplo.com")

    def test_send_password_link(self):
        customer = f.user(email="esqueceu@exemplo.com")
        self.client.post(reverse("dashboard:customer_detail", args=[customer.pk]), {"action": "send_reset"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["esqueceu@exemplo.com"])

    def test_non_superuser_admin_cannot_edit_staff(self):
        other_staff = f.staff("Estoquista")
        resp = self.client.post(reverse("dashboard:customer_detail", args=[other_staff.pk]), {
            "action": "edit", "full_name": "Hack", "email": "hack@exemplo.com"})
        self.assertEqual(resp.status_code, 403)

    def test_manager_and_attendance_cannot_create_or_edit(self):
        customer = f.user()
        for role in ("Gestor comercial", "Atendimento"):
            self.client.force_login(f.staff(role))
            self.assertEqual(self.client.get(reverse("dashboard:user_new")).status_code, 403)
            resp = self.client.post(reverse("dashboard:customer_detail", args=[customer.pk]),
                                    {"action": "edit", "full_name": "X", "email": "x@exemplo.com"})
            self.assertEqual(resp.status_code, 403)

    def test_block_requires_reason_and_cannot_block_self(self):
        customer = f.user()
        self.client.post(reverse("dashboard:customer_detail", args=[customer.pk]), {"action": "block", "reason": ""})
        customer.refresh_from_db()
        self.assertTrue(customer.is_active)
        self.admin.is_superuser = True
        self.admin.save()
        self.client.post(reverse("dashboard:customer_detail", args=[self.admin.pk]), {"action": "block", "reason": "x"})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
