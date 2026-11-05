from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import PublicIdModel, TimeStampedModel


class Cart(PublicIdModel, TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE,
                                related_name="cart")
    session_key = models.CharField(max_length=64, blank=True, db_index=True)
    coupon = models.ForeignKey("promotions.Coupon", null=True, blank=True, on_delete=models.SET_NULL)
    shipping_cep = models.CharField(max_length=9, blank=True)
    shipping_choice = models.CharField(max_length=40, blank=True)

    class Meta:
        verbose_name = "carrinho"
        verbose_name_plural = "carrinhos"

    def __str__(self):
        return f"Carrinho {self.public_id}"

    @property
    def item_count(self):
        return sum(i.quantity for i in self.items.all())


class CartItem(TimeStampedModel):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.CASCADE, related_name="+")
    quantity = models.PositiveIntegerField(default=1)
    personalization = models.OneToOneField("personalization.PersonalizationRequest", null=True, blank=True,
                                           on_delete=models.CASCADE, related_name="cart_item")

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["cart", "variant"], condition=Q(personalization__isnull=True),
                                    name="unique_plain_cart_item"),
            models.CheckConstraint(condition=Q(quantity__gte=1), name="cart_item_quantity_positive"),
        ]

    def __str__(self):
        return f"{self.quantity}× {self.variant_id}"
