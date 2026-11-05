"""
Carrinho persistente (sessão + usuário) e cálculo de totais.

Preços e estoque são SEMPRE recalculados no servidor a partir do banco.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction

from apps.catalog.models import Product, ProductVariant
from apps.catalog.pricing import PriceInfo, PricingEngine
from apps.core.utils import money
from apps.promotions.services import CouponError, CouponResult, PricedLine, evaluate_coupon

from .models import Cart, CartItem

SESSION_KEY = "cart_id"
MAX_QTY_PER_ITEM = 20


class CartError(Exception):
    pass


def _session_key(request) -> str:
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


def get_cart(request, create: bool = False) -> Cart | None:
    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
        if cart is None and create:
            cart = Cart.objects.create(user=request.user)
        return cart
    cart_id = request.session.get(SESSION_KEY)
    cart = Cart.objects.filter(public_id=cart_id, user__isnull=True).first() if cart_id else None
    if cart is None and create:
        cart = Cart.objects.create(session_key=_session_key(request))
        request.session[SESSION_KEY] = str(cart.public_id)
    return cart


@transaction.atomic
def merge_session_cart_into_user(request, user):
    cart_id = request.session.get(SESSION_KEY)
    if not cart_id:
        return
    anon = Cart.objects.filter(public_id=cart_id, user__isnull=True).first()
    request.session.pop(SESSION_KEY, None)
    if anon is None:
        return
    user_cart, _ = Cart.objects.get_or_create(user=user)
    for item in anon.items.all():
        if item.personalization_id:
            item.cart = user_cart
            item.save(update_fields=["cart"])
            continue
        existing = user_cart.items.filter(variant=item.variant, personalization__isnull=True).first()
        if existing:
            existing.quantity = min(existing.quantity + item.quantity, MAX_QTY_PER_ITEM)
            existing.save(update_fields=["quantity", "updated_at"])
        else:
            item.cart = user_cart
            item.save(update_fields=["cart"])
    if anon.coupon_id and not user_cart.coupon_id:
        user_cart.coupon_id = anon.coupon_id
        user_cart.save(update_fields=["coupon"])
    anon.delete()


def add_item(cart: Cart, variant: ProductVariant, quantity: int = 1) -> CartItem:
    if quantity < 1:
        raise CartError("Quantidade inválida.")
    if not variant.is_active or variant.product.status != Product.Status.ACTIVE:
        raise CartError("Este produto não está disponível.")
    item = cart.items.filter(variant=variant, personalization__isnull=True).first()
    new_qty = (item.quantity if item else 0) + quantity
    if new_qty > MAX_QTY_PER_ITEM:
        raise CartError(f"Máximo de {MAX_QTY_PER_ITEM} unidades por item.")
    if variant.available < new_qty:
        if variant.available <= 0:
            raise CartError("Esta variação está esgotada.")
        raise CartError(f"Só temos {variant.available} unidade(s) disponível(is) nesta variação.")
    if item:
        item.quantity = new_qty
        item.save(update_fields=["quantity", "updated_at"])
        return item
    return CartItem.objects.create(cart=cart, variant=variant, quantity=quantity)


def update_quantity(cart: Cart, item_id: int, quantity: int):
    item = cart.items.select_related("variant").filter(pk=item_id).first()
    if item is None:
        raise CartError("Item não encontrado.")
    if quantity <= 0:
        remove_item(cart, item_id)
        return None
    if item.personalization_id and quantity != item.quantity:
        raise CartError("A quantidade de peças personalizadas é definida na solicitação.")
    if quantity > MAX_QTY_PER_ITEM:
        raise CartError(f"Máximo de {MAX_QTY_PER_ITEM} unidades por item.")
    if item.variant.available < quantity:
        raise CartError(f"Só temos {item.variant.available} unidade(s) disponível(is).")
    item.quantity = quantity
    item.save(update_fields=["quantity", "updated_at"])
    return item


def remove_item(cart: Cart, item_id: int):
    item = cart.items.filter(pk=item_id).first()
    if item is None:
        return
    if item.personalization_id:
        from apps.personalization.models import PersonalizationRequest

        PersonalizationRequest.objects.filter(pk=item.personalization_id, status="in_cart").update(status="approved")
    item.delete()


@dataclass
class CartLine:
    item: CartItem
    variant: ProductVariant
    quantity: int
    price: PriceInfo
    personalization_fee: Decimal = Decimal("0")
    problem: str = ""

    @property
    def product(self):
        return self.variant.product

    @property
    def unit_price(self) -> Decimal:
        return self.price.final

    @property
    def unit_total(self) -> Decimal:
        return self.price.final + self.personalization_fee

    @property
    def line_total(self) -> Decimal:
        return money(self.unit_total * self.quantity)


@dataclass
class CartSummary:
    cart: Cart | None
    lines: list[CartLine] = field(default_factory=list)
    coupon_result: CouponResult | None = None
    coupon_error: str = ""
    shipping_cost: Decimal | None = None

    @property
    def is_empty(self):
        return not self.lines

    @property
    def count(self):
        return sum(l.quantity for l in self.lines)

    @property
    def subtotal_original(self) -> Decimal:
        return money(sum((l.price.base * l.quantity for l in self.lines), Decimal("0")))

    @property
    def products_subtotal(self) -> Decimal:
        return money(sum((l.price.final * l.quantity for l in self.lines), Decimal("0")))

    @property
    def promotion_discount(self) -> Decimal:
        return self.subtotal_original - self.products_subtotal

    @property
    def personalization_total(self) -> Decimal:
        return money(sum((l.personalization_fee * l.quantity for l in self.lines), Decimal("0")))

    @property
    def coupon_discount(self) -> Decimal:
        return self.coupon_result.discount if self.coupon_result else Decimal("0.00")

    @property
    def free_shipping(self) -> bool:
        return bool(self.coupon_result and self.coupon_result.free_shipping)

    @property
    def effective_shipping(self) -> Decimal | None:
        if self.shipping_cost is None:
            return None
        return Decimal("0.00") if self.free_shipping else self.shipping_cost

    @property
    def total(self) -> Decimal:
        total = self.products_subtotal + self.personalization_total - self.coupon_discount
        total += self.effective_shipping or Decimal("0")
        return money(max(total, Decimal("0")))

    @property
    def has_problems(self):
        return any(l.problem for l in self.lines)

    def priced_lines(self) -> list[PricedLine]:
        return [
            PricedLine(product_id=l.product.pk, category_id=l.product.category_id, unit_price=l.price.final,
                       original_unit_price=l.price.base, quantity=l.quantity, extra_fee=l.personalization_fee)
            for l in self.lines
        ]


def summarize(cart: Cart | None, *, user=None, email: str = "", engine: PricingEngine | None = None) -> CartSummary:
    summary = CartSummary(cart=cart)
    if cart is None:
        return summary
    engine = engine or PricingEngine()
    items = cart.items.select_related(
        "variant__product__category", "variant__color", "variant__size", "personalization__placement"
    ).prefetch_related("variant__product__images", "variant__product__collections")
    for item in items:
        variant = item.variant
        problem = ""
        if not variant.is_active or variant.product.status != Product.Status.ACTIVE:
            problem = "Produto indisponível — remova do carrinho."
        elif variant.available < item.quantity:
            problem = ("Esgotado." if variant.available == 0
                       else f"Só restam {variant.available} unidade(s). Ajuste a quantidade.")
        fee = item.personalization.fee if item.personalization_id else Decimal("0")
        summary.lines.append(CartLine(item=item, variant=variant, quantity=item.quantity,
                                      price=engine.price_for(variant.product, variant),
                                      personalization_fee=fee, problem=problem))
    if cart.coupon_id and summary.lines:
        try:
            summary.coupon_result = evaluate_coupon(cart.coupon, summary.priced_lines(), user=user, email=email)
        except CouponError as exc:
            summary.coupon_error = str(exc)
    return summary
