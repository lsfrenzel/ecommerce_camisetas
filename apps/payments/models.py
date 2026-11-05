from django.db import models

from apps.core.models import TimeStampedModel


class Payment(TimeStampedModel):
    class Provider(models.TextChoices):
        MERCADOPAGO = "mercadopago", "Mercado Pago"
        MANUAL = "manual", "Registro manual"

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="payments")
    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.MERCADOPAGO)
    preference_id = models.CharField(max_length=120, blank=True, db_index=True)
    checkout_url = models.URLField(max_length=500, blank=True)
    external_id = models.CharField("ID no gateway", max_length=60, blank=True, db_index=True)
    status = models.CharField(max_length=30, default="created", db_index=True)
    status_detail = models.CharField(max_length=80, blank=True)
    method = models.CharField("meio de pagamento", max_length=40, blank=True)
    installments = models.PositiveSmallIntegerField(null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    amount_received = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    fee_amount = models.DecimalField("tarifas", max_digits=12, decimal_places=2, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    live_mode = models.BooleanField(default=False)
    # Somente dados não sensíveis do gateway (sem dados de cartão).
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "pagamento"
        verbose_name_plural = "pagamentos"
        constraints = [
            models.UniqueConstraint(fields=["provider", "external_id"], condition=~models.Q(external_id=""),
                                    name="unique_gateway_payment"),
        ]

    def __str__(self):
        return f"{self.get_provider_display()} {self.external_id or self.preference_id} ({self.status})"


class PaymentEvent(models.Model):
    """Notificação recebida do gateway (registro + idempotência)."""

    provider = models.CharField(max_length=20, default="mercadopago")
    idempotency_key = models.CharField(max_length=200)
    topic = models.CharField(max_length=40, blank=True)
    action = models.CharField(max_length=60, blank=True)
    resource_id = models.CharField(max_length=60, blank=True, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    signature_valid = models.BooleanField(default=False)
    processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=255, blank=True)
    attempts = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "evento de pagamento"
        verbose_name_plural = "eventos de pagamento"
        constraints = [
            models.UniqueConstraint(fields=["provider", "idempotency_key"], name="unique_payment_event"),
        ]

    def __str__(self):
        return f"{self.topic}:{self.resource_id}"
