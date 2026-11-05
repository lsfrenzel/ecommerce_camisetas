from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import TimeStampedModel


class DiscountKind(models.TextChoices):
    PERCENT = "percent", "Percentual (%)"
    FIXED = "fixed", "Valor fixo (R$)"


class Promotion(TimeStampedModel):
    """Promoção automática aplicada ao preço de produtos, categorias ou coleções."""

    name = models.CharField("nome", max_length=100)
    kind = models.CharField("tipo", max_length=10, choices=DiscountKind.choices, default=DiscountKind.PERCENT)
    value = models.DecimalField("valor", max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    applies_to_all = models.BooleanField("aplicar a toda a loja", default=False)
    products = models.ManyToManyField("catalog.Product", blank=True, related_name="promotions", verbose_name="produtos")
    categories = models.ManyToManyField("catalog.Category", blank=True, related_name="promotions", verbose_name="categorias")
    collections = models.ManyToManyField("catalog.Collection", blank=True, related_name="promotions", verbose_name="coleções")
    starts_at = models.DateTimeField("início", null=True, blank=True)
    ends_at = models.DateTimeField("fim", null=True, blank=True)
    is_active = models.BooleanField("ativa", default=True)
    label = models.CharField("etiqueta exibida", max_length=30, blank=True, help_text="Ex.: -20% DROP")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "promoção"
        verbose_name_plural = "promoções"
        constraints = [
            models.CheckConstraint(condition=Q(value__gt=0), name="promotion_value_positive"),
            models.CheckConstraint(
                condition=~Q(kind="percent") | Q(value__lte=90), name="promotion_percent_max_90"
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.kind == DiscountKind.PERCENT and self.value and self.value > 90:
            raise ValidationError({"value": "Descontos percentuais acima de 90% não são permitidos."})
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "O fim deve ser posterior ao início."})

    def is_live(self, now=None):
        now = now or timezone.now()
        return (
            self.is_active
            and (self.starts_at is None or self.starts_at <= now)
            and (self.ends_at is None or self.ends_at >= now)
        )

    @classmethod
    def live(cls, now=None):
        now = now or timezone.now()
        return cls.objects.filter(is_active=True).filter(
            Q(starts_at__isnull=True) | Q(starts_at__lte=now)
        ).filter(Q(ends_at__isnull=True) | Q(ends_at__gte=now))


class Coupon(TimeStampedModel):
    class Kind(models.TextChoices):
        PERCENT = "percent", "Percentual (%)"
        FIXED = "fixed", "Valor fixo (R$)"
        FREE_SHIPPING = "free_shipping", "Frete grátis"

    code = models.CharField("código", max_length=30, unique=True)
    description = models.CharField("descrição interna", max_length=150, blank=True)
    kind = models.CharField("tipo", max_length=15, choices=Kind.choices, default=Kind.PERCENT)
    value = models.DecimalField("valor", max_digits=10, decimal_places=2, default=0,
                                validators=[MinValueValidator(Decimal("0"))])
    max_discount = models.DecimalField("desconto máximo (R$)", max_digits=10, decimal_places=2, null=True, blank=True)
    min_order_value = models.DecimalField("pedido mínimo (R$)", max_digits=10, decimal_places=2, default=0)
    max_uses = models.PositiveIntegerField("limite total de usos", null=True, blank=True)
    max_uses_per_customer = models.PositiveIntegerField("limite por cliente", null=True, blank=True, default=1)
    starts_at = models.DateTimeField("início", null=True, blank=True)
    ends_at = models.DateTimeField("fim", null=True, blank=True)
    is_active = models.BooleanField("ativo", default=True)
    stackable_with_promotions = models.BooleanField(
        "cumulativo com promoções", default=False,
        help_text="Se desmarcado, o cupom só incide sobre itens que não estão em promoção.")
    first_order_only = models.BooleanField("somente primeira compra", default=False)
    products = models.ManyToManyField("catalog.Product", blank=True, verbose_name="restrito aos produtos")
    categories = models.ManyToManyField("catalog.Category", blank=True, verbose_name="restrito às categorias")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "cupom"
        verbose_name_plural = "cupons"
        constraints = [
            models.CheckConstraint(condition=~Q(kind="percent") | (Q(value__gt=0) & Q(value__lte=100)),
                                   name="coupon_percent_range"),
            models.CheckConstraint(condition=~Q(kind="fixed") | Q(value__gt=0), name="coupon_fixed_positive"),
        ]

    def __str__(self):
        return self.code

    def clean(self):
        self.code = (self.code or "").strip().upper()
        if self.kind == self.Kind.PERCENT and not (0 < self.value <= 100):
            raise ValidationError({"value": "Percentual deve estar entre 0,01 e 100."})
        if self.kind == self.Kind.FIXED and self.value <= 0:
            raise ValidationError({"value": "Informe um valor maior que zero."})
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "O fim deve ser posterior ao início."})

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)

    def uses_count(self):
        return self.redemptions.exclude(order__status__in=["cancelled"]).count()


class CouponRedemption(models.Model):
    coupon = models.ForeignKey(Coupon, on_delete=models.PROTECT, related_name="redemptions")
    order = models.OneToOneField("orders.Order", on_delete=models.CASCADE, related_name="coupon_redemption")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    email = models.EmailField()
    discount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "uso de cupom"
        verbose_name_plural = "usos de cupons"
        indexes = [models.Index(fields=["coupon", "email"])]

    def __str__(self):
        return f"{self.coupon.code} · {self.order_id}"
