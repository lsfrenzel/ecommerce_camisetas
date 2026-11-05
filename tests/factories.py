"""Construtores simples de dados para os testes (sem dependências extras)."""

import io
import itertools
from decimal import Decimal

from django.contrib.auth.models import Group
from PIL import Image

from apps.accounts.models import User
from apps.cart.models import Cart, CartItem
from apps.catalog.models import Category, Color, Product, ProductVariant, Size
from apps.dashboard.forms import ensure_groups
from apps.inventory.models import InventoryMovement
from apps.inventory.services import record_movement
from apps.shipping.models import ShippingMethod

_seq = itertools.count(1)


def user(email=None, password="Senha-Forte-123", **extra):
    n = next(_seq)
    return User.objects.create_user(email=email or f"cliente{n}@exemplo.com", password=password,
                                    full_name=extra.pop("full_name", f"Cliente {n}"), **extra)


def staff(role="Administrador geral", **extra):
    ensure_groups()
    u = user(is_staff=True, **extra)
    u.groups.add(Group.objects.get(name=role))
    return u


def category(name="Camisetas"):
    obj, _ = Category.objects.get_or_create(slug=name.lower().replace(" ", "-"), defaults={"name": name})
    return obj


def color(name="Preta", hex="#111111"):
    obj, _ = Color.objects.get_or_create(name=name, defaults={"hex": hex})
    return obj


def size(name="M", position=2):
    obj, _ = Size.objects.get_or_create(name=name, defaults={"position": position})
    return obj


def product(name=None, price="100.00", cost="40.00", status=Product.Status.ACTIVE, cat=None, **extra):
    n = next(_seq)
    return Product.objects.create(
        name=name or f"Camiseta Teste {n}", sku_base=f"TST{n}", category=cat or category(), price=Decimal(price),
        cost_price=Decimal(cost), status=status, **extra)


def variant(prod=None, stock=10, col=None, sz=None, fit="oversized", **extra):
    prod = prod or product()
    n = next(_seq)
    v = ProductVariant.objects.create(product=prod, sku=f"SKU{n}", color=col or color(), size=sz or size(f"T{n}", n),
                                      fit=fit, **extra)
    if stock:
        record_movement(v.pk, InventoryMovement.Kind.ENTRY, stock, reason="teste")
        v.refresh_from_db()
    return v


def cart_with(variant_obj, qty=1, user_obj=None):
    c = Cart.objects.create(user=user_obj, session_key="" if user_obj else f"s{next(_seq)}")
    CartItem.objects.create(cart=c, variant=variant_obj, quantity=qty)
    return c


def shipping_fixed(price="20.00", states="", free_above=None):
    return ShippingMethod.objects.create(name="Frete fixo", kind=ShippingMethod.Kind.FIXED, price=Decimal(price),
                                         states=states, free_above=free_above, days_min=1, days_max=5)


def png_bytes(w=2000, h=2000, fmt="PNG", color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, fmt)
    return buf.getvalue()


def checkout_data(**overrides):
    from apps.orders.services import CheckoutData

    data = dict(email="comprador@exemplo.com", full_name="Maria da Silva", phone="(11) 98888-7777", cpf="",
                cep="05860-000", street="Rua Teste", number="100", complement="", neighborhood="Capão Redondo",
                city="São Paulo", state="SP", shipping_code="", notes="")
    data.update(overrides)
    return CheckoutData(**data)


class FakeGateway:
    """Gateway falso para testes: nunca é usado fora da suíte de testes."""

    is_production = False
    configured = True

    def __init__(self):
        self.payments = {}
        self.preferences = []

    def create_preference(self, order):
        self.preferences.append(order.pk)
        return {"id": f"pref-{order.pk}", "url": f"https://sandbox.mercadopago.com.br/checkout?pref={order.pk}"}

    def get_payment(self, payment_id):
        from apps.payments.gateway import GatewayError

        if str(payment_id) not in self.payments:
            raise GatewayError("não encontrado")
        return self.payments[str(payment_id)]

    def search_by_reference(self, reference):
        return [p for p in self.payments.values() if p.get("external_reference") == reference]

    def add_payment(self, order, payment_id="123456", status="approved", amount=None, live_mode=False, **extra):
        data = {"id": int(payment_id), "status": status, "status_detail": "accredited", "external_reference": str(order.public_id),
                "transaction_amount": float(amount if amount is not None else order.total), "currency_id": "BRL",
                "payment_type_id": "bank_transfer", "payment_method_id": "pix", "installments": 1,
                "date_approved": "2026-11-05T10:00:00.000-03:00" if status == "approved" else None,
                "live_mode": live_mode, "card": {"last_four_digits": "1234"}, **extra}
        self.payments[str(payment_id)] = data
        return data
