import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import storages
from django.db import models
from django.urls import reverse

from apps.core.models import PublicIdModel, TimeStampedModel


def private_storage():
    return storages["private"]


def upload_to(instance, filename):
    ext = Path(filename).suffix.lower()[:6]
    return f"personalization/{uuid.uuid4().hex}{ext}"


class PrintPlacement(models.Model):
    class Side(models.TextChoices):
        FRONT = "front", "Frente"
        BACK = "back", "Costas"

    name = models.CharField("nome", max_length=60)
    code = models.SlugField("código", unique=True)
    side = models.CharField("lado", max_length=5, choices=Side.choices, default=Side.FRONT)
    description = models.CharField("descrição", max_length=160, blank=True)
    fee = models.DecimalField("valor adicional", max_digits=8, decimal_places=2, default=0)
    max_width_cm = models.PositiveSmallIntegerField("largura máxima (cm)", default=28)
    # Área de impressão na prévia, em % da imagem da camiseta.
    box_left = models.PositiveSmallIntegerField(default=30)
    box_top = models.PositiveSmallIntegerField(default=25)
    box_width = models.PositiveSmallIntegerField(default=40)
    box_height = models.PositiveSmallIntegerField(default=45)
    is_active = models.BooleanField("ativa", default=True)
    position = models.PositiveIntegerField("ordem", default=0)

    class Meta:
        ordering = ["position", "name"]
        verbose_name = "posição de estampa"
        verbose_name_plural = "posições de estampa"

    def __str__(self):
        return self.name


class PersonalizationRequest(PublicIdModel, TimeStampedModel):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Enviada"
        IN_REVIEW = "in_review", "Em análise"
        APPROVED = "approved", "Aprovada — pronta para compra"
        REJECTED = "rejected", "Recusada"
        IN_CART = "in_cart", "No carrinho"
        ORDERED = "ordered", "Comprada"
        CANCELLED = "cancelled", "Cancelada"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="personalizations")
    session_key = models.CharField(max_length=64, blank=True)
    name = models.CharField("nome", max_length=150)
    email = models.EmailField("e-mail")
    phone = models.CharField("WhatsApp / telefone", max_length=20, blank=True)

    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+", verbose_name="modelo")
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.PROTECT, related_name="+",
                                verbose_name="cor e tamanho")
    quantity = models.PositiveIntegerField("quantidade", default=1)
    placement = models.ForeignKey(PrintPlacement, on_delete=models.PROTECT, verbose_name="posição da estampa")

    image = models.FileField("arte enviada", upload_to=upload_to, storage=private_storage, blank=True)
    image_original_name = models.CharField(max_length=200, blank=True)
    image_width = models.PositiveIntegerField(null=True, blank=True)
    image_height = models.PositiveIntegerField(null=True, blank=True)
    low_resolution = models.BooleanField("resolução abaixo do recomendado", default=False)

    custom_text = models.CharField("texto personalizado", max_length=120, blank=True)
    text_color = models.CharField("cor do texto", max_length=7, blank=True)
    instructions = models.TextField("instruções adicionais", blank=True, max_length=2000)

    fee = models.DecimalField("valor da personalização (unitário)", max_digits=8, decimal_places=2, default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SUBMITTED, db_index=True)
    admin_notes = models.TextField("resposta / observações para o cliente", blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rights_confirmed = models.BooleanField("declara possuir direitos sobre a arte", default=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "pedido de personalização"
        verbose_name_plural = "pedidos de personalização"
        permissions = [("review_personalization", "Pode aprovar/recusar personalizações")]

    def __str__(self):
        return f"Personalização {str(self.public_id)[:8]} — {self.name}"

    def get_absolute_url(self):
        return reverse("personalization:detail", args=[self.public_id])

    @property
    def can_add_to_cart(self):
        return self.status == self.Status.APPROVED
