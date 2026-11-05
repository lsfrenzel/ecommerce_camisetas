from django.conf import settings
from django.db import models
from django.db.models import Q


class InventoryMovement(models.Model):
    class Kind(models.TextChoices):
        ENTRY = "entry", "Entrada de mercadoria"
        EXIT = "exit", "Saída manual"
        ADJUSTMENT = "adjustment", "Ajuste de inventário"
        SALE = "sale", "Venda"
        RETURN = "return", "Devolução / cancelamento"
        LOSS = "loss", "Perda / avaria"

    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.CASCADE, related_name="movements",
                                verbose_name="variação")
    kind = models.CharField("tipo", max_length=12, choices=Kind.choices, db_index=True)
    quantity = models.IntegerField("quantidade", help_text="Positivo para entrada, negativo para saída.")
    stock_after = models.PositiveIntegerField("estoque após")
    unit_cost = models.DecimalField("custo unitário", max_digits=10, decimal_places=2, null=True, blank=True)
    reason = models.CharField("motivo", max_length=255, blank=True)
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="inventory_movements")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="+", verbose_name="responsável")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "movimentação de estoque"
        verbose_name_plural = "movimentações de estoque"
        constraints = [models.CheckConstraint(condition=~Q(quantity=0), name="movement_quantity_not_zero")]

    def __str__(self):
        return f"{self.get_kind_display()} {self.quantity:+d} · {self.variant.sku}"


class InventoryReservation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Ativa"
        CONSUMED = "consumed", "Consumida (venda)"
        RELEASED = "released", "Liberada"

    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.CASCADE, related_name="reservations")
    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="reservations")
    quantity = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "reserva de estoque"
        verbose_name_plural = "reservas de estoque"
        indexes = [models.Index(fields=["status", "expires_at"])]
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="reservation_quantity_positive")]

    def __str__(self):
        return f"Reserva {self.quantity}× {self.variant.sku} ({self.get_status_display()})"
