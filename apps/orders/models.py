from decimal import Decimal

from django.conf import settings
from django.core import signing
from django.db import models
from django.db.models import Q
from django.urls import reverse

from apps.core.models import PublicIdModel, TimeStampedModel
from apps.core.utils import UF_CHOICES


class OrderStatus(models.TextChoices):
    AWAITING_PAYMENT = "awaiting_payment", "Aguardando pagamento"
    PAID = "paid", "Pago"
    CUSTOMIZING = "customizing", "Em personalização"
    IN_PRODUCTION = "in_production", "Em produção"
    READY_TO_SHIP = "ready_to_ship", "Pronto para envio"
    SHIPPED = "shipped", "Enviado"
    DELIVERED = "delivered", "Entregue"
    CANCELLED = "cancelled", "Cancelado"
    REFUNDED = "refunded", "Reembolsado"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    IN_PROCESS = "in_process", "Em análise"
    APPROVED = "approved", "Aprovado"
    REJECTED = "rejected", "Recusado"
    CANCELLED = "cancelled", "Cancelado"
    REFUNDED = "refunded", "Reembolsado"
    CHARGED_BACK = "charged_back", "Contestado (chargeback)"


# Transições permitidas pelo painel (status financeiros são definidos pelo gateway).
ALLOWED_TRANSITIONS = {
    OrderStatus.AWAITING_PAYMENT: {OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.CUSTOMIZING, OrderStatus.IN_PRODUCTION, OrderStatus.READY_TO_SHIP,
                       OrderStatus.CANCELLED, OrderStatus.REFUNDED},
    OrderStatus.CUSTOMIZING: {OrderStatus.IN_PRODUCTION, OrderStatus.READY_TO_SHIP, OrderStatus.CANCELLED,
                              OrderStatus.REFUNDED},
    OrderStatus.IN_PRODUCTION: {OrderStatus.READY_TO_SHIP, OrderStatus.CANCELLED, OrderStatus.REFUNDED},
    OrderStatus.READY_TO_SHIP: {OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.CANCELLED,
                                OrderStatus.REFUNDED},
    OrderStatus.SHIPPED: {OrderStatus.DELIVERED, OrderStatus.REFUNDED},
    OrderStatus.DELIVERED: {OrderStatus.REFUNDED},
    OrderStatus.CANCELLED: set(),
    OrderStatus.REFUNDED: set(),
}

PAID_STATUSES = [
    OrderStatus.PAID, OrderStatus.CUSTOMIZING, OrderStatus.IN_PRODUCTION, OrderStatus.READY_TO_SHIP,
    OrderStatus.SHIPPED, OrderStatus.DELIVERED,
]


class Order(PublicIdModel, TimeStampedModel):
    class Source(models.TextChoices):
        WEB = "web", "Loja virtual"
        MANUAL = "manual", "Manual"
        SHOPEE = "shopee", "Shopee"
        MERCADO_LIVRE = "mercado_livre", "Mercado Livre"

    number = models.CharField("número", max_length=20, unique=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="orders", verbose_name="cliente")
    source = models.CharField("origem", max_length=20, choices=Source.choices, default=Source.WEB)
    external_id = models.CharField("ID externo (marketplace)", max_length=80, blank=True, db_index=True)

    status = models.CharField("status", max_length=20, choices=OrderStatus.choices,
                              default=OrderStatus.AWAITING_PAYMENT, db_index=True)
    payment_status = models.CharField("situação financeira", max_length=20, choices=PaymentStatus.choices,
                                      default=PaymentStatus.PENDING, db_index=True)
    needs_attention = models.BooleanField("exige atenção", default=False, db_index=True)
    attention_reason = models.CharField(max_length=255, blank=True)

    # Dados do comprador (cópia histórica)
    email = models.EmailField("e-mail")
    customer_name = models.CharField("nome", max_length=150)
    phone = models.CharField("telefone", max_length=20)
    cpf = models.CharField("CPF", max_length=14, blank=True)

    # Endereço de entrega (cópia histórica)
    ship_recipient = models.CharField("destinatário", max_length=150)
    ship_cep = models.CharField("CEP", max_length=9)
    ship_street = models.CharField("endereço", max_length=200)
    ship_number = models.CharField("número", max_length=20)
    ship_complement = models.CharField("complemento", max_length=100, blank=True)
    ship_neighborhood = models.CharField("bairro", max_length=100)
    ship_city = models.CharField("cidade", max_length=100)
    ship_state = models.CharField("UF", max_length=2, choices=UF_CHOICES)

    shipping_method = models.ForeignKey("shipping.ShippingMethod", null=True, blank=True, on_delete=models.SET_NULL)
    shipping_option_code = models.CharField(max_length=40, blank=True)
    shipping_name = models.CharField("modalidade de entrega", max_length=120)
    shipping_days_max = models.PositiveSmallIntegerField(null=True, blank=True)
    shipping_cost = models.DecimalField("frete", max_digits=10, decimal_places=2, default=Decimal("0"))

    subtotal = models.DecimalField("subtotal", max_digits=12, decimal_places=2)
    promotion_discount = models.DecimalField("descontos de promoção", max_digits=12, decimal_places=2, default=0)
    coupon_discount = models.DecimalField("desconto do cupom", max_digits=12, decimal_places=2, default=0)
    coupon_code = models.CharField("cupom", max_length=30, blank=True)
    personalization_total = models.DecimalField("personalização", max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField("total", max_digits=12, decimal_places=2)

    customer_notes = models.TextField("observações do cliente", blank=True, max_length=1000)
    internal_notes = models.TextField("observações internas", blank=True)

    reservation_expires_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField("pago em", null=True, blank=True, db_index=True)
    cancelled_at = models.DateTimeField("cancelado em", null=True, blank=True)
    cancel_reason = models.CharField("motivo do cancelamento", max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "pedido"
        verbose_name_plural = "pedidos"
        permissions = [
            ("change_order_status", "Pode alterar status de pedidos"),
            ("cancel_order", "Pode cancelar pedidos"),
            ("register_manual_payment", "Pode registrar pagamento manual"),
            ("view_reports", "Pode ver relatórios comerciais"),
            ("view_financials", "Pode ver custos e lucro bruto"),
        ]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["email"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(total__gte=0), name="order_total_non_negative"),
            models.CheckConstraint(condition=Q(subtotal__gte=0), name="order_subtotal_non_negative"),
        ]

    def __str__(self):
        return self.number or str(self.public_id)

    def save(self, *args, **kwargs):
        creating = self.pk is None
        super().save(*args, **kwargs)
        if creating and not self.number:
            self.number = f"{10000 + self.pk}"
            super().save(update_fields=["number"])

    def get_absolute_url(self):
        return reverse("orders:detail", args=[self.public_id])

    @property
    def is_paid(self):
        return self.status in PAID_STATUSES or self.status == OrderStatus.REFUNDED and self.paid_at is not None

    @property
    def can_pay(self):
        return self.status == OrderStatus.AWAITING_PAYMENT

    @property
    def discount_total(self):
        return self.promotion_discount + self.coupon_discount

    @property
    def shipping_address_line(self):
        comp = f" — {self.ship_complement}" if self.ship_complement else ""
        return f"{self.ship_street}, {self.ship_number}{comp} · {self.ship_neighborhood} · {self.ship_city}/{self.ship_state} · CEP {self.ship_cep}"

    def access_token(self) -> str:
        return signing.dumps(str(self.public_id), salt="order-access")

    @staticmethod
    def check_access_token(token: str, public_id) -> bool:
        try:
            return signing.loads(token, salt="order-access", max_age=60 * 60 * 24 * 180) == str(public_id)
        except signing.BadSignature:
            return False

    def allowed_next_statuses(self):
        return sorted(ALLOWED_TRANSITIONS.get(self.status, set()), key=lambda s: list(OrderStatus.values).index(s))


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey("catalog.ProductVariant", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="order_items")
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="order_items")
    # Cópia histórica — não muda se o produto for alterado.
    product_name = models.CharField(max_length=140)
    sku = models.CharField(max_length=60)
    color_name = models.CharField(max_length=40)
    size_name = models.CharField(max_length=10)
    fit = models.CharField(max_length=20)
    category_name = models.CharField(max_length=80, blank=True)
    image_url = models.CharField(max_length=500, blank=True)
    original_unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    quantity = models.PositiveIntegerField()
    personalization = models.ForeignKey("personalization.PersonalizationRequest", null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name="order_items")
    personalization_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["id"]
        verbose_name = "item do pedido"
        verbose_name_plural = "itens do pedido"
        constraints = [models.CheckConstraint(condition=Q(quantity__gte=1), name="order_item_quantity_positive")]

    def __str__(self):
        return f"{self.quantity}× {self.product_name} ({self.sku})"

    @property
    def unit_total(self):
        return self.unit_price + self.personalization_fee

    @property
    def variant_label(self):
        return f"{self.fit} / {self.color_name} / {self.size_name}"


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="history")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    note = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="+")
    customer_notified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = "histórico do pedido"
        verbose_name_plural = "histórico dos pedidos"

    def __str__(self):
        return f"{self.order} {self.from_status} → {self.to_status}"

    @property
    def to_label(self):
        try:
            return OrderStatus(self.to_status).label
        except ValueError:
            return self.to_status
