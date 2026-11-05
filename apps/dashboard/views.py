import csv
import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import DataRequest, SupportRequest, User
from apps.catalog.models import Product, ProductVariant
from apps.core.audit import diff_instance, log_action
from apps.core.models import AuditLog
from apps.inventory import services as inventory
from apps.inventory.models import InventoryMovement
from apps.orders.models import PAID_STATUSES, Order, OrderStatus
from apps.orders.notifications import send_templated
from apps.orders.services import CheckoutError, cancel_order, change_status
from apps.payments.gateway import GatewayError, GatewayNotConfigured
from apps.personalization.models import PersonalizationRequest
from apps.shipping.models import Shipment

from . import metrics
from .forms import (BulkPriceForm, GenerateVariantsForm, MovementForm, OrderStatusForm, ProductForm,
                    ProductImageInline, ProductVariantInline, RoleAssignForm, ShipmentForm, StaffUserForm,
                    ensure_groups, role_of)
from .permissions import ROLE_PERMISSIONS, staff_required

PRICE_FIELDS = ["price", "compare_at_price", "cost_price", "sale_price", "sale_starts_at", "sale_ends_at"]


def _page(request, qs, per=25):
    return Paginator(qs, per).get_page(request.GET.get("page"))


# ----------------------------------------------------------------------------- Dashboard
@staff_required()
def home(request):
    period = metrics.resolve_period(request.GET)
    can_finance = request.user.has_perm("orders.view_reports")
    context = {
        "period": period, "periods": metrics.PERIODS, "status": metrics.status_counts(),
        "recent_orders": Order.objects.order_by("-created_at")[:8] if request.user.has_perm("orders.view_order") else [],
        "low_stock": metrics.low_stock(8), "section": "home", "can_finance": can_finance,
    }
    if can_finance:
        context.update({
            "kpi": metrics.overview(period), "series": json.dumps(metrics.daily_series(period)),
            "top_products": metrics.top_products(period, 6),
            "can_cost": request.user.has_perm("orders.view_financials"),
        })
    return render(request, "dashboard/home.html", context)


# ----------------------------------------------------------------------------- Produtos
@staff_required("catalog.view_product")
def product_list(request):
    qs = Product.objects.select_related("category").annotate(
        stock_total=Sum("variants__stock"), variant_count=Count("variants", distinct=True)).order_by("-created_at")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku_base__icontains=q) | Q(variants__sku__icontains=q)).distinct()
    status = request.GET.get("status", "")
    if status:
        qs = qs.filter(status=status)
    else:
        qs = qs.exclude(status=Product.Status.ARCHIVED)
    return render(request, "dashboard/products/list.html", {
        "page": _page(request, qs), "q": q, "status": status, "statuses": Product.Status.choices, "section": "products"})


@staff_required("catalog.view_product")
def product_edit(request, pk=None):
    product = get_object_or_404(Product, pk=pk) if pk else None
    perm = "catalog.change_product" if product else "catalog.add_product"
    if request.method == "POST" and not request.user.has_perm(perm):
        raise PermissionDenied
    before = {f: getattr(product, f) for f in PRICE_FIELDS} if product else {}
    form = ProductForm(request.POST or None, instance=product)
    if not request.user.has_perm("orders.view_financials"):
        form.fields["cost_price"].disabled = True  # custo só é editável por quem vê dados financeiros
    variants = ProductVariantInline(request.POST or None, instance=product or Product(), prefix="variants")
    images = ProductImageInline(request.POST or None, request.FILES or None, instance=product or Product(), prefix="images")
    if request.method == "POST":
        if form.is_valid() and variants.is_valid() and images.is_valid():
            with transaction.atomic():
                obj = form.save()
                variants.instance = obj
                images.instance = obj
                variants.save()
                images.save()
                after = {f: getattr(obj, f) for f in PRICE_FIELDS}
                if product is None:
                    log_action(actor=request.user, action=AuditLog.Action.CREATE, obj=obj, request=request)
                else:
                    changes = diff_instance(before, after)
                    if changes:
                        log_action(actor=request.user, action=AuditLog.Action.PRICE_CHANGE, obj=obj,
                                   changes=changes, request=request, message="Edição de produto")
            messages.success(request, "Produto salvo.")
            return redirect("dashboard:product_edit", pk=obj.pk)
        messages.error(request, "Corrija os erros destacados.")
    return render(request, "dashboard/products/form.html", {
        "form": form, "variants": variants, "images": images, "product": product, "section": "products",
        "generate_form": GenerateVariantsForm() if product else None,
    })


@staff_required("catalog.add_productvariant")
@require_POST
def product_generate_variants(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = GenerateVariantsForm(request.POST)
    if form.is_valid():
        created = 0
        fit = form.cleaned_data["fit"]
        for color in form.cleaned_data["colors"]:
            for size in form.cleaned_data["sizes"]:
                sku = f"{product.sku_base}-{'OVR' if fit == 'oversized' else 'REG'}-{color.slug[:3].upper()}-{size.name}"
                variant, was_created = ProductVariant.objects.get_or_create(
                    product=product, color=color, size=size, fit=fit, defaults={"sku": sku})
                if was_created:
                    created += 1
                    qty = form.cleaned_data["initial_stock"]
                    if qty:
                        inventory.record_movement(variant.pk, InventoryMovement.Kind.ENTRY, qty, user=request.user,
                                                  reason="Estoque inicial", request=request)
        messages.success(request, f"{created} variação(ões) criada(s).")
    else:
        messages.error(request, "Selecione cores e tamanhos.")
    return redirect("dashboard:product_edit", pk=pk)


@staff_required("catalog.add_product")
@require_POST
def product_duplicate(request, pk):
    original = get_object_or_404(Product, pk=pk)
    with transaction.atomic():
        collections = list(original.collections.all())
        variants = list(original.variants.all())
        copy = Product.objects.get(pk=pk)
        copy.pk = None
        copy.id = None
        import uuid

        copy.public_id = uuid.uuid4()
        copy.slug = ""
        copy.name = f"{original.name} (cópia)"
        base = f"{original.sku_base}-C"
        n = 1
        while Product.objects.filter(sku_base=f"{base}{n}").exists():
            n += 1
        copy.sku_base = f"{base}{n}"
        copy.status = Product.Status.DRAFT
        copy.sold_count = 0
        copy.save()
        copy.collections.set(collections)
        for v in variants:
            ProductVariant.objects.create(product=copy, sku=f"{copy.sku_base}-{v.sku.split('-', 1)[-1]}"[:60],
                                          color=v.color, size=v.size, fit=v.fit, price_override=v.price_override,
                                          low_stock_threshold=v.low_stock_threshold, stock=0)
        log_action(actor=request.user, action=AuditLog.Action.CREATE, obj=copy, request=request,
                   message=f"Duplicado de {original.sku_base}")
    messages.success(request, "Produto duplicado como rascunho (sem estoque e sem imagens).")
    return redirect("dashboard:product_edit", pk=copy.pk)


@staff_required("catalog.change_product")
@require_POST
def product_archive(request, pk):
    product = get_object_or_404(Product, pk=pk)
    old = product.status
    product.status = Product.Status.ARCHIVED if product.status != Product.Status.ARCHIVED else Product.Status.INACTIVE
    product.save(update_fields=["status", "updated_at"])
    log_action(actor=request.user, action=AuditLog.Action.UPDATE, obj=product, request=request,
               changes={"status": [old, product.status]})
    messages.success(request, "Produto arquivado." if product.status == Product.Status.ARCHIVED else "Produto restaurado como inativo.")
    return redirect("dashboard:products")


@staff_required(["catalog.change_product", "orders.view_reports"])
def bulk_price(request):
    form = BulkPriceForm(request.POST or None, initial={"products": request.GET.getlist("p")})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            for p in form.cleaned_data["products"]:
                old = p.price
                p.price = form.new_price(old)
                if p.sale_price is not None and p.sale_price >= p.price:
                    p.sale_price = None
                p.save(update_fields=["price", "sale_price", "updated_at"])
                log_action(actor=request.user, action=AuditLog.Action.PRICE_CHANGE, obj=p, request=request,
                           changes={"price": [old, p.price]}, message="Alteração de preço em lote")
        messages.success(request, f"Preços atualizados ({len(form.cleaned_data['products'])} produtos).")
        return redirect("dashboard:products")
    return render(request, "dashboard/products/bulk_price.html", {"form": form, "section": "products"})


# ----------------------------------------------------------------------------- Estoque
@staff_required("inventory.view_inventorymovement")
def inventory_view(request):
    qs = ProductVariant.objects.select_related("product", "color", "size").order_by("product__name", "color__position", "size__position")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(sku__icontains=q) | Q(product__name__icontains=q))
    if request.GET.get("baixo"):
        ids = [v.pk for v in metrics.low_stock(500)]
        qs = qs.filter(pk__in=ids)
    form = MovementForm(request.POST or None, initial={"variant": request.GET.get("v")})
    if request.method == "POST":
        if not request.user.has_perm("inventory.add_inventorymovement"):
            raise PermissionDenied
        if form.is_valid():
            d = form.cleaned_data
            try:
                inventory.record_movement(d["variant"].pk, d["kind"], d["quantity"], user=request.user,
                                          reason=d["reason"], unit_cost=d.get("unit_cost"), request=request)
                messages.success(request, "Movimentação registrada.")
                return redirect(request.get_full_path())
            except inventory.InventoryError as exc:
                form.add_error("quantity", str(exc))
    return render(request, "dashboard/inventory.html", {
        "page": _page(request, qs, 40), "form": form, "q": q, "section": "inventory",
        "movements": InventoryMovement.objects.select_related("variant__product", "user", "order")[:30],
        "stale": metrics.stale_products()[:10],
    })


@staff_required("inventory.view_inventorymovement")
def inventory_history(request):
    qs = InventoryMovement.objects.select_related("variant__product", "user", "order")
    if request.GET.get("sku"):
        qs = qs.filter(variant__sku__icontains=request.GET["sku"])
    if request.GET.get("tipo"):
        qs = qs.filter(kind=request.GET["tipo"])
    if request.GET.get("csv"):
        return _csv("movimentacoes-estoque.csv", ["Data", "SKU", "Produto", "Tipo", "Qtd", "Estoque após", "Motivo", "Usuário"],
                    ([timezone.localtime(m.created_at).strftime("%d/%m/%Y %H:%M"), m.variant.sku, m.variant.product.name,
                      m.get_kind_display(), m.quantity, m.stock_after, m.reason, m.user.email if m.user else ""] for m in qs[:20000]))
    return render(request, "dashboard/inventory_history.html", {"page": _page(request, qs, 50), "kinds": InventoryMovement.Kind.choices, "section": "inventory"})


# ----------------------------------------------------------------------------- Pedidos
@staff_required("orders.view_order")
def order_list(request):
    qs = Order.objects.order_by("-created_at")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(email__icontains=q) | Q(customer_name__icontains=q)
                       | Q(shipment__tracking_code__icontains=q))
    status = request.GET.get("status", "")
    if status == "atencao":
        qs = qs.filter(needs_attention=True)
    elif status:
        qs = qs.filter(status=status)
    if request.GET.get("csv") and request.user.has_perm("orders.view_reports"):
        return _csv("pedidos.csv", ["Número", "Data", "Cliente", "E-mail", "Status", "Pagamento", "Subtotal", "Descontos", "Frete", "Total"],
                    ([o.number, timezone.localtime(o.created_at).strftime("%d/%m/%Y %H:%M"), o.customer_name, o.email,
                      o.get_status_display(), o.get_payment_status_display(), o.subtotal, o.discount_total, o.shipping_cost,
                      o.total] for o in qs[:20000]))
    return render(request, "dashboard/orders/list.html", {
        "page": _page(request, qs), "q": q, "status": status, "statuses": OrderStatus.choices, "section": "orders"})


@staff_required("orders.view_order")
def order_detail(request, number):
    order = get_object_or_404(Order, number=number)
    shipment = Shipment.objects.filter(order=order).first()
    status_form = OrderStatusForm(order=order)
    ship_form = ShipmentForm(instance=shipment)
    return render(request, "dashboard/orders/detail.html", {
        "order": order, "items": order.items.select_related("personalization"), "history": order.history.select_related("actor"),
        "payments": order.payments.all(), "shipment": shipment, "status_form": status_form, "ship_form": ship_form,
        "movements": order.inventory_movements.select_related("variant"), "section": "orders",
        "can_cost": request.user.has_perm("orders.view_financials"),
    })


@staff_required("orders.change_order_status")
@require_POST
def order_status(request, number):
    order = get_object_or_404(Order, number=number)
    form = OrderStatusForm(request.POST, order=order)
    if form.is_valid():
        new = form.cleaned_data["status"]
        if new == OrderStatus.CANCELLED and not request.user.has_perm("orders.cancel_order"):
            raise PermissionDenied
        try:
            change_status(order, new, actor=request.user, note=form.cleaned_data["note"],
                          notify=form.cleaned_data["notify"], request=request)
            messages.success(request, "Status atualizado.")
        except CheckoutError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Transição inválida.")
    return redirect("dashboard:order_detail", number=number)


@staff_required("orders.cancel_order")
@require_POST
def order_cancel(request, number):
    order = get_object_or_404(Order, number=number)
    try:
        cancel_order(order, actor=request.user, reason=request.POST.get("reason", "Cancelado pela equipe")[:255],
                     restock=request.POST.get("restock") == "1", request=request)
        messages.success(request, "Pedido cancelado.")
    except CheckoutError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard:order_detail", number=number)


@staff_required("shipping.change_shipment")
@require_POST
def order_shipment(request, number):
    order = get_object_or_404(Order, number=number)
    shipment, _ = Shipment.objects.get_or_create(order=order)
    form = ShipmentForm(request.POST, instance=shipment)
    if form.is_valid():
        form.save()
        log_action(actor=request.user, action=AuditLog.Action.UPDATE, obj=order, request=request,
                   message=f"Envio atualizado: {shipment.get_status_display()} {shipment.tracking_code}")
        if request.POST.get("notify"):
            from apps.orders.notifications import notify_order

            notify_order(order, "status")
        messages.success(request, "Dados de envio salvos.")
    else:
        messages.error(request, "Verifique os dados de envio.")
    return redirect("dashboard:order_detail", number=number)


@staff_required("orders.register_manual_payment")
@require_POST
def order_manual_payment(request, number):
    from apps.payments.services import register_manual_payment

    order = get_object_or_404(Order, number=number)
    note = request.POST.get("note", "").strip()
    if len(note) < 5:
        messages.error(request, "Descreva a forma e a comprovação do pagamento.")
    else:
        try:
            register_manual_payment(order, actor=request.user, note=note, request=request)
            messages.success(request, "Pagamento manual registrado.")
        except GatewayError as exc:
            messages.error(request, str(exc))
    return redirect("dashboard:order_detail", number=number)


@staff_required("orders.view_order")
@require_POST
def order_reconcile(request, number):
    from apps.payments.services import reconcile_order

    order = get_object_or_404(Order, number=number)
    try:
        reconcile_order(order)
        messages.success(request, "Pagamentos consultados no Mercado Pago.")
    except (GatewayError, GatewayNotConfigured) as exc:
        messages.error(request, f"Não foi possível consultar: {exc}")
    return redirect("dashboard:order_detail", number=number)


@staff_required("orders.change_order")
@require_POST
def order_resolve_attention(request, number):
    order = get_object_or_404(Order, number=number)
    order.needs_attention = False
    order.internal_notes = (order.internal_notes + f"\n[{timezone.localtime():%d/%m %H:%M}] Pendência resolvida por {request.user.email}: {order.attention_reason}").strip()
    order.attention_reason = ""
    order.save(update_fields=["needs_attention", "attention_reason", "internal_notes", "updated_at"])
    log_action(actor=request.user, action=AuditLog.Action.UPDATE, obj=order, request=request, message="Pendência resolvida")
    return redirect("dashboard:order_detail", number=number)


# ----------------------------------------------------------------------------- Clientes
@staff_required("accounts.view_user")
def customer_list(request):
    qs = User.objects.filter(is_staff=False).select_related("profile").annotate(
        order_count=Count("orders", filter=Q(orders__status__in=PAID_STATUSES), distinct=True),
        spent=Sum("orders__total", filter=Q(orders__status__in=PAID_STATUSES)),
    ).order_by("-date_joined")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(email__icontains=q) | Q(full_name__icontains=q) | Q(profile__phone__icontains=q))
    return render(request, "dashboard/customers/list.html", {"page": _page(request, qs), "q": q, "section": "customers"})


@staff_required("accounts.view_user")
def customer_detail(request, pk):
    customer = get_object_or_404(User.objects.select_related("profile"), pk=pk)
    orders = customer.orders.order_by("-created_at")
    spent = orders.filter(status__in=PAID_STATUSES).aggregate(v=Sum("total"))["v"] or Decimal("0")
    if request.method == "POST":
        if not request.user.has_perm("accounts.change_user"):
            raise PermissionDenied
        if customer.is_staff and not request.user.is_superuser:
            raise PermissionDenied
        action = request.POST.get("action")
        if action == "block":
            customer.is_active = False
            customer.profile.blocked_reason = request.POST.get("reason", "")[:255]
            log_action(actor=request.user, action=AuditLog.Action.ACCOUNT_BLOCK, obj=customer, request=request,
                       message=f"Bloqueio: {customer.profile.blocked_reason}")
            messages.success(request, "Conta bloqueada.")
        elif action == "unblock":
            customer.is_active = True
            customer.profile.blocked_reason = ""
            log_action(actor=request.user, action=AuditLog.Action.ACCOUNT_BLOCK, obj=customer, request=request,
                       message="Desbloqueio")
            messages.success(request, "Conta desbloqueada.")
        elif action == "notes":
            customer.profile.staff_notes = request.POST.get("staff_notes", "")[:5000]
            messages.success(request, "Observações salvas.")
        customer.save()
        customer.profile.save()
        return redirect("dashboard:customer_detail", pk=pk)
    return render(request, "dashboard/customers/detail.html", {
        "customer": customer, "orders": orders, "spent": spent, "section": "customers"})


# ----------------------------------------------------------------------------- Personalização
@staff_required("personalization.view_personalizationrequest")
def personalization_list(request):
    qs = PersonalizationRequest.objects.select_related("product", "placement", "variant__color", "variant__size")
    status = request.GET.get("status", "")
    if status:
        qs = qs.filter(status=status)
    return render(request, "dashboard/personalization/list.html", {
        "page": _page(request, qs), "status": status, "statuses": PersonalizationRequest.Status.choices,
        "section": "personalization"})


@staff_required("personalization.view_personalizationrequest")
def personalization_detail(request, public_id):
    p = get_object_or_404(PersonalizationRequest.objects.select_related("product", "placement", "variant__color", "variant__size"),
                          public_id=public_id)
    if request.method == "POST":
        if not request.user.has_perm("personalization.review_personalization"):
            raise PermissionDenied
        action = request.POST.get("action")
        p.admin_notes = request.POST.get("admin_notes", "")[:3000]
        try:
            fee = Decimal(request.POST.get("fee", p.fee))
            if fee >= 0:
                p.fee = fee
        except Exception:  # noqa: BLE001
            pass
        if action in ("approve", "reject", "review") and p.status in ("submitted", "in_review", "approved", "rejected"):
            p.status = {"approve": "approved", "reject": "rejected", "review": "in_review"}[action]
            p.reviewed_by = request.user
            p.reviewed_at = timezone.now()
        p.save()
        if action in ("approve", "reject"):
            send_templated(p.email, "Sua personalização foi " + ("aprovada" if action == "approve" else "analisada"),
                           "personalization_update", {"p": p, "link": request.build_absolute_uri(p.get_absolute_url())})
        log_action(actor=request.user, action=AuditLog.Action.UPDATE, obj=p, request=request, message=f"Personalização: {p.get_status_display()}")
        messages.success(request, "Personalização atualizada.")
        return redirect("dashboard:personalization_detail", public_id=public_id)
    return render(request, "dashboard/personalization/detail.html", {"p": p, "section": "personalization"})


# ----------------------------------------------------------------------------- Relatórios
@staff_required("orders.view_reports")
def reports(request):
    period = metrics.resolve_period(request.GET)
    report = request.GET.get("r", "vendas")
    can_cost = request.user.has_perm("orders.view_financials")
    data = {
        "vendas": lambda: metrics.daily_series(period),
        "produtos": lambda: metrics.top_products(period, 50),
        "categorias": lambda: metrics.breakdown(period, "category_name"),
        "tamanhos": lambda: metrics.breakdown(period, "size_name"),
        "cores": lambda: metrics.breakdown(period, "color_name"),
        "cupons": lambda: metrics.coupons_used(period),
        "estoque": lambda: metrics.low_stock(500),
        "cancelados": lambda: list(metrics.cancelled_orders(period)[:500]),
        "sem-giro": lambda: list(metrics.stale_products()[:200]),
    }
    if report not in data:
        report = "vendas"
    rows = data[report]()
    if request.GET.get("csv"):
        return _report_csv(report, rows, period)
    return render(request, "dashboard/reports.html", {
        "period": period, "periods": metrics.PERIODS, "report": report, "rows": rows, "kpi": metrics.overview(period),
        "series": json.dumps(rows) if report == "vendas" else "null", "can_cost": can_cost, "section": "reports",
        "reports": [("vendas", "Vendas por período"), ("produtos", "Mais vendidos"), ("categorias", "Receita por categoria"),
                    ("tamanhos", "Vendas por tamanho"), ("cores", "Vendas por cor"), ("cupons", "Cupons utilizados"),
                    ("estoque", "Estoque baixo"), ("cancelados", "Cancelados / reembolsados"), ("sem-giro", "Produtos sem giro")],
    })


def _csv(filename, header, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("﻿")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(header)
    for row in rows:
        writer.writerow([_csv_safe(c) for c in row])
    return response


def _csv_safe(value):
    """Evita injeção de fórmulas em planilhas (CSV injection)."""
    s = "" if value is None else str(value)
    if s and s[0] in "=+-@\t\r" and not s.lstrip("-").replace(".", "", 1).replace(",", "", 1).isdigit():
        return "'" + s
    return s


def _report_csv(report, rows, period):
    name = f"relatorio-{report}-{timezone.localtime(period.start):%Y%m%d}-{timezone.localtime(period.end):%Y%m%d}.csv"
    if report == "vendas":
        return _csv(name, ["Dia", "Pedidos pagos", "Receita"], zip(rows["labels"], rows["counts"], rows["totals"]))
    if report == "produtos":
        return _csv(name, ["Produto", "Unidades", "Receita"], ((r["product_name"], r["units"], r["revenue"]) for r in rows))
    if report in ("categorias", "tamanhos", "cores"):
        key = {"categorias": "category_name", "tamanhos": "size_name", "cores": "color_name"}[report]
        return _csv(name, ["Grupo", "Unidades", "Receita"], ((r[key], r["units"], r["revenue"]) for r in rows))
    if report == "cupons":
        return _csv(name, ["Cupom", "Usos", "Desconto", "Receita"], ((r["coupon_code"], r["uses"], r["discount"], r["revenue"]) for r in rows))
    if report == "estoque":
        return _csv(name, ["SKU", "Produto", "Cor", "Tamanho", "Físico", "Reservado", "Disponível", "Mínimo"],
                    ((v.sku, v.product.name, v.color.name, v.size.name, v.stock, v.reserved, v.available, v.low_stock_threshold) for v in rows))
    if report == "cancelados":
        return _csv(name, ["Pedido", "Data", "Cliente", "Status", "Total", "Motivo"],
                    ((o.number, timezone.localtime(o.created_at).strftime("%d/%m/%Y"), o.customer_name, o.get_status_display(), o.total, o.cancel_reason) for o in rows))
    return _csv(name, ["Produto", "SKU base", "Estoque total"], ((p.name, p.sku_base, p.stock_total) for p in rows))


# ----------------------------------------------------------------------------- Equipe
@staff_required("auth.change_group")
def team(request):
    ensure_groups()
    staff = User.objects.filter(Q(is_staff=True) | Q(groups__isnull=False)).distinct().prefetch_related("groups")
    form = StaffUserForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        if d["role"] == "Administrador geral" and not request.user.is_superuser:
            raise PermissionDenied
        user = User.objects.create_user(email=d["email"], password=d["password"], full_name=d["full_name"], is_staff=True)
        user.groups.set([Group.objects.get(name=d["role"])])
        log_action(actor=request.user, action=AuditLog.Action.PERMISSION_CHANGE, obj=user, request=request,
                   changes={"role": [None, d["role"]]}, message="Novo membro da equipe")
        messages.success(request, "Membro da equipe criado.")
        return redirect("dashboard:team")
    return render(request, "dashboard/team.html", {
        "staff": [(u, role_of(u)) for u in staff], "form": form, "roles": ROLE_PERMISSIONS, "section": "team",
        "role_form": RoleAssignForm()})


@staff_required("auth.change_group")
@require_POST
def team_role(request, pk):
    member = get_object_or_404(User, pk=pk)
    if member.is_superuser or member == request.user:
        messages.error(request, "Não é possível alterar o papel deste usuário por aqui.")
        return redirect("dashboard:team")
    form = RoleAssignForm(request.POST)
    if form.is_valid():
        role = form.cleaned_data["role"]
        if role == "Administrador geral" and not request.user.is_superuser:
            raise PermissionDenied
        old = role_of(member)
        member.groups.remove(*Group.objects.filter(name__in=ROLE_PERMISSIONS))
        if role:
            member.groups.add(Group.objects.get(name=role))
            member.is_staff = True
        else:
            member.is_staff = False
        member.save(update_fields=["is_staff"])
        log_action(actor=request.user, action=AuditLog.Action.PERMISSION_CHANGE, obj=member, request=request,
                   changes={"role": [old, role or "Cliente"]})
        messages.success(request, "Papel atualizado.")
    return redirect("dashboard:team")


# ----------------------------------------------------------------------------- Atendimento / LGPD / Auditoria
@staff_required("accounts.view_supportrequest")
def support_list(request):
    if request.method == "POST":
        if not request.user.has_perm("accounts.change_supportrequest"):
            raise PermissionDenied
        ticket = get_object_or_404(SupportRequest, pk=request.POST.get("id"))
        ticket.staff_reply = request.POST.get("reply", "")[:3000]
        ticket.status = request.POST.get("status", ticket.status)
        ticket.save()
        if ticket.staff_reply:
            send_templated(ticket.user.email, f"Resposta: {ticket.subject}", "support_reply", {"ticket": ticket})
        messages.success(request, "Solicitação atualizada.")
        return redirect("dashboard:support")
    qs = SupportRequest.objects.select_related("user", "order")
    return render(request, "dashboard/support.html", {"page": _page(request, qs), "statuses": SupportRequest.Status.choices,
                                                      "section": "support"})


@staff_required("accounts.view_datarequest")
def data_requests(request):
    if request.method == "POST":
        if not request.user.has_perm("accounts.change_datarequest"):
            raise PermissionDenied
        req = get_object_or_404(DataRequest, pk=request.POST.get("id"))
        req.status = request.POST.get("status", req.status)
        req.response = request.POST.get("response", "")[:2000]
        req.resolved_at = timezone.now() if req.status != DataRequest.Status.PENDING else None
        req.save()
        if request.POST.get("anonymize") == "1" and req.kind == DataRequest.Kind.DELETION and req.user and request.user.is_superuser:
            from apps.accounts.services import anonymize_user

            anonymize_user(req.user)
        log_action(actor=request.user, action=AuditLog.Action.DATA_REQUEST, obj=req, request=request,
                   message=f"{req.get_kind_display()} → {req.get_status_display()}")
        messages.success(request, "Solicitação atualizada.")
        return redirect("dashboard:data_requests")
    return render(request, "dashboard/data_requests.html", {
        "page": _page(request, DataRequest.objects.select_related("user")), "statuses": DataRequest.Status.choices,
        "section": "lgpd"})


@staff_required("core.view_auditlog")
def audit_log(request):
    qs = AuditLog.objects.select_related("actor")
    if request.GET.get("acao"):
        qs = qs.filter(action=request.GET["acao"])
    if request.GET.get("q"):
        qs = qs.filter(Q(object_repr__icontains=request.GET["q"]) | Q(actor__email__icontains=request.GET["q"]))
    return render(request, "dashboard/audit.html", {"page": _page(request, qs, 50), "actions": AuditLog.Action.choices,
                                                    "section": "audit"})


@staff_required("content.view_newslettersubscriber")
def newsletter_export(request):
    from apps.content.models import NewsletterSubscriber

    qs = NewsletterSubscriber.objects.filter(unsubscribed_at__isnull=True, consent=True)
    return _csv("newsletter.csv", ["E-mail", "Consentimento em", "Origem"],
                ((s.email, timezone.localtime(s.consent_at).strftime("%d/%m/%Y %H:%M") if s.consent_at else "", s.source) for s in qs))
