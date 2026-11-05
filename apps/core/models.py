import uuid

from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("criado em", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        abstract = True


class PublicIdModel(models.Model):
    """Identificador público não sequencial para uso em URLs."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        abstract = True


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", "Criação"
        UPDATE = "update", "Alteração"
        DELETE = "delete", "Exclusão"
        PRICE_CHANGE = "price_change", "Alteração de preço"
        STOCK_MOVEMENT = "stock_movement", "Movimentação de estoque"
        PERMISSION_CHANGE = "permission_change", "Alteração de permissões"
        ORDER_STATUS = "order_status", "Status de pedido"
        ORDER_CANCEL = "order_cancel", "Cancelamento"
        PAYMENT = "payment", "Pagamento"
        ACCOUNT_BLOCK = "account_block", "Bloqueio de conta"
        SETTINGS = "settings", "Configurações"
        DATA_REQUEST = "data_request", "Solicitação LGPD"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    action = models.CharField("ação", max_length=32, choices=Action.choices, db_index=True)
    object_type = models.CharField("tipo", max_length=80, db_index=True)
    object_id = models.CharField("id", max_length=64, blank=True)
    object_repr = models.CharField("objeto", max_length=255, blank=True)
    changes = models.JSONField("alterações", default=dict, blank=True)
    message = models.CharField("descrição", max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "registro de auditoria"
        verbose_name_plural = "registros de auditoria"
        indexes = [models.Index(fields=["object_type", "object_id"])]

    def __str__(self):
        return f"{self.get_action_display()} · {self.object_repr}"
