from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.core.utils import UF_CHOICES, format_cep, validate_cep


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("E-mail é obrigatório.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if not extra["is_staff"] or not extra["is_superuser"]:
            raise ValueError("Superusuário precisa de is_staff e is_superuser.")
        return self._create_user(email, password, **extra)

    def get_by_natural_key(self, email):
        return self.get(email__iexact=email)


class User(AbstractUser):
    username = None
    first_name = None
    last_name = None
    email = models.EmailField("e-mail", unique=True)
    full_name = models.CharField("nome completo", max_length=150)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    objects = UserManager()

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"
        ordering = ["-date_joined"]

    def __str__(self):
        return self.full_name or self.email

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return (self.full_name or self.email).split(" ")[0]

    @property
    def is_team_member(self) -> bool:
        return self.is_active and self.is_staff


class CustomerProfile(TimeStampedModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    phone = models.CharField("telefone", max_length=20, blank=True)
    cpf = models.CharField("CPF", max_length=14, blank=True)
    birth_date = models.DateField("data de nascimento", null=True, blank=True)
    marketing_opt_in = models.BooleanField("aceita comunicações de marketing", default=False)
    marketing_opt_in_at = models.DateTimeField(null=True, blank=True)
    order_updates_whatsapp = models.BooleanField("atualizações de pedido por WhatsApp", default=False)
    blocked_reason = models.CharField("motivo do bloqueio", max_length=255, blank=True)
    staff_notes = models.TextField("observações internas", blank=True)

    class Meta:
        verbose_name = "perfil de cliente"
        verbose_name_plural = "perfis de clientes"

    def __str__(self):
        return f"Perfil de {self.user}"

    def set_marketing(self, value: bool):
        if value and not self.marketing_opt_in:
            self.marketing_opt_in_at = timezone.now()
        if not value:
            self.marketing_opt_in_at = None
        self.marketing_opt_in = value


class Address(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    label = models.CharField("identificação", max_length=40, blank=True, help_text="Ex.: Casa, Trabalho")
    recipient_name = models.CharField("destinatário", max_length=150)
    cep = models.CharField("CEP", max_length=9, validators=[validate_cep])
    street = models.CharField("endereço", max_length=200)
    number = models.CharField("número", max_length=20)
    complement = models.CharField("complemento", max_length=100, blank=True)
    neighborhood = models.CharField("bairro", max_length=100)
    city = models.CharField("cidade", max_length=100)
    state = models.CharField("UF", max_length=2, choices=UF_CHOICES)
    is_default = models.BooleanField("endereço principal", default=False)

    class Meta:
        verbose_name = "endereço"
        verbose_name_plural = "endereços"
        ordering = ["-is_default", "-updated_at"]

    def __str__(self):
        return f"{self.street}, {self.number} — {self.city}/{self.state}"

    def save(self, *args, **kwargs):
        self.cep = format_cep(self.cep)
        super().save(*args, **kwargs)
        if self.is_default:
            Address.objects.filter(user=self.user).exclude(pk=self.pk).update(is_default=False)


class SupportRequest(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Aberta"
        ANSWERED = "answered", "Respondida"
        CLOSED = "closed", "Encerrada"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="support_requests")
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.SET_NULL, verbose_name="pedido")
    subject = models.CharField("assunto", max_length=150)
    message = models.TextField("mensagem", max_length=3000)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True)
    staff_reply = models.TextField("resposta", blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "solicitação de suporte"
        verbose_name_plural = "solicitações de suporte"

    def __str__(self):
        return self.subject


class DataRequest(TimeStampedModel):
    """Solicitações de titulares de dados (LGPD, art. 18)."""

    class Kind(models.TextChoices):
        ACCESS = "access", "Acesso / cópia dos dados"
        CORRECTION = "correction", "Correção de dados"
        DELETION = "deletion", "Exclusão / anonimização"
        REVOKE = "revoke", "Revogação de consentimento"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        DONE = "done", "Atendida"
        DENIED = "denied", "Negada (obrigação legal)"

    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="data_requests")
    email = models.EmailField()
    kind = models.CharField("tipo", max_length=12, choices=Kind.choices)
    details = models.TextField("detalhes", blank=True, max_length=2000)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    response = models.TextField("resposta", blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "solicitação LGPD"
        verbose_name_plural = "solicitações LGPD"

    def __str__(self):
        return f"{self.get_kind_display()} — {self.email}"
