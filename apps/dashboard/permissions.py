"""Autorização do painel: exige equipe ativa + permissões reais do Django (não apenas ocultar botões)."""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

ROLE_PERMISSIONS = {
    "Administrador geral": "__all__",
    "Gestor comercial": [
        "catalog.view_product", "catalog.add_product", "catalog.change_product", "catalog.delete_product",
        "catalog.view_productvariant", "catalog.add_productvariant", "catalog.change_productvariant",
        "catalog.view_productimage", "catalog.add_productimage", "catalog.change_productimage", "catalog.delete_productimage",
        "catalog.view_category", "catalog.add_category", "catalog.change_category",
        "catalog.view_collection", "catalog.add_collection", "catalog.change_collection",
        "catalog.view_color", "catalog.add_color", "catalog.change_color",
        "catalog.view_size", "catalog.add_size", "catalog.change_size",
        "catalog.view_sizechart", "catalog.add_sizechart", "catalog.change_sizechart",
        "promotions.view_coupon", "promotions.add_coupon", "promotions.change_coupon",
        "promotions.view_promotion", "promotions.add_promotion", "promotions.change_promotion",
        "orders.view_order", "orders.change_order", "orders.change_order_status", "orders.cancel_order",
        "orders.view_reports", "orders.view_financials",
        "inventory.view_inventorymovement",
        "content.view_brandsettings", "content.change_brandsettings",
        "content.view_banner", "content.add_banner", "content.change_banner", "content.delete_banner",
        "content.view_page", "content.add_page", "content.change_page",
        "content.view_faq", "content.add_faq", "content.change_faq", "content.delete_faq",
        "content.view_newslettersubscriber",
        "shipping.view_shippingmethod", "shipping.add_shippingmethod", "shipping.change_shippingmethod",
        "shipping.view_shipment", "shipping.change_shipment",
        "personalization.view_personalizationrequest", "personalization.change_personalizationrequest",
        "personalization.review_personalization",
        "personalization.view_printplacement", "personalization.add_printplacement", "personalization.change_printplacement",
        "accounts.view_user",
    ],
    "Estoquista": [
        "catalog.view_product", "catalog.view_productvariant", "catalog.change_productvariant",
        "inventory.view_inventorymovement", "inventory.add_inventorymovement",
        "orders.view_order", "orders.change_order_status",
        "shipping.view_shipment", "shipping.change_shipment",
    ],
    "Atendimento": [
        "orders.view_order", "orders.change_order_status",
        "shipping.view_shipment", "shipping.change_shipment",
        "accounts.view_user", "accounts.view_supportrequest", "accounts.change_supportrequest",
        "accounts.view_datarequest", "accounts.change_datarequest",
        "personalization.view_personalizationrequest", "personalization.change_personalizationrequest",
        "personalization.review_personalization",
        "catalog.view_product",
    ],
}


def is_team(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active and user.is_staff)


def staff_required(perm: str | list[str] | None = None):
    """Decorator para views do painel. Sem login → login; sem permissão → 403."""
    perms = [perm] if isinstance(perm, str) else list(perm or [])

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not is_team(request.user):
                raise PermissionDenied
            if perms and not request.user.has_perms(perms):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


class StaffPermissionMixin:
    permission_required: str | list[str] | None = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not is_team(request.user):
            raise PermissionDenied
        perms = self.get_permission_required()
        if perms and not request.user.has_perms(perms):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_permission_required(self):
        p = self.permission_required
        return [p] if isinstance(p, str) else list(p or [])
