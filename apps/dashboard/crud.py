"""CRUD genérico do painel para cadastros simples (com permissões e auditoria)."""

from __future__ import annotations

from dataclasses import dataclass, field

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import ProtectedError
from django.forms import modelform_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse

from apps.core.audit import log_action
from apps.core.models import AuditLog

from .forms import CouponForm, PromotionForm, StyledModelForm
from .permissions import is_team


@dataclass
class Crud:
    slug: str
    model: type
    title: str
    singular: str
    columns: list[tuple[str, str]]
    fields: list[str] | None = None
    form_class: type | None = None
    search: list[str] = field(default_factory=list)
    section: str = "content"
    can_delete: bool = True
    help: str = ""

    @property
    def opts(self):
        return self.model._meta

    def perm(self, action):
        return f"{self.opts.app_label}.{action}_{self.opts.model_name}"

    def get_form_class(self):
        if self.form_class:
            return self.form_class
        return modelform_factory(self.model, form=StyledModelForm, fields=self.fields)

    def check(self, request, action):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())
        if not is_team(request.user) or not request.user.has_perm(self.perm(action)):
            raise PermissionDenied
        return None

    # Views ------------------------------------------------------------------
    def list_view(self, request):
        resp = self.check(request, "view")
        if resp:
            return resp
        qs = self.model.objects.all()
        q = request.GET.get("q", "").strip()
        if q and self.search:
            from django.db.models import Q

            cond = Q()
            for f in self.search:
                cond |= Q(**{f"{f}__icontains": q})
            qs = qs.filter(cond)
        page = Paginator(qs, 30).get_page(request.GET.get("page"))
        rows = [(obj, [self._value(obj, c) for c, _ in self.columns]) for obj in page.object_list]
        return render(request, "dashboard/crud_list.html", {
            "crud": self, "page": page, "rows": rows, "q": q, "section": self.section,
            "can_add": request.user.has_perm(self.perm("add")),
        })

    def edit_view(self, request, pk=None):
        obj = get_object_or_404(self.model, pk=pk) if pk else None
        resp = self.check(request, "change" if obj else "add") if request.method == "POST" else self.check(request, "view")
        if resp:
            return resp
        Form = self.get_form_class()
        form = Form(request.POST or None, request.FILES or None, instance=obj)
        if request.method == "POST" and form.is_valid():
            before = {name: form.initial.get(name) for name in form.changed_data} if obj else {}
            saved = form.save()
            changes = {name: [str(before.get(name)), str(form.cleaned_data.get(name))] for name in form.changed_data} if obj else {}
            action = AuditLog.Action.UPDATE if obj else AuditLog.Action.CREATE
            if any(k in changes for k in ("value", "kind", "price")):
                action = AuditLog.Action.PRICE_CHANGE
            log_action(actor=request.user, action=action, obj=saved, changes=changes, request=request)
            messages.success(request, f"{self.singular.capitalize()} salvo(a).")
            return redirect(reverse(f"dashboard:{self.slug}_list"))
        return render(request, "dashboard/crud_form.html", {
            "crud": self, "form": form, "obj": obj, "section": self.section,
            "can_delete": bool(obj) and self.can_delete and request.user.has_perm(self.perm("delete")),
        })

    def delete_view(self, request, pk):
        resp = self.check(request, "delete")
        if resp:
            return resp
        if request.method != "POST" or not self.can_delete:
            raise PermissionDenied
        obj = get_object_or_404(self.model, pk=pk)
        label = str(obj)
        try:
            obj.delete()
            log_action(actor=request.user, action=AuditLog.Action.DELETE, object_type=self.opts.label,
                       object_id=str(pk), request=request, message=label)
            messages.success(request, f"{self.singular.capitalize()} excluído(a).")
        except ProtectedError:
            messages.error(request, "Não é possível excluir: há registros vinculados. Desative em vez de excluir.")
        return redirect(reverse(f"dashboard:{self.slug}_list"))

    def urls(self):
        return [
            path(f"{self.slug}/", self.list_view, name=f"{self.slug}_list"),
            path(f"{self.slug}/novo/", self.edit_view, name=f"{self.slug}_new"),
            path(f"{self.slug}/<int:pk>/", self.edit_view, name=f"{self.slug}_edit"),
            path(f"{self.slug}/<int:pk>/excluir/", self.delete_view, name=f"{self.slug}_delete"),
        ]

    @staticmethod
    def _value(obj, attr):
        value = obj
        for part in attr.split("."):
            value = getattr(value, part, "")
            if callable(value):
                value = value()
        if isinstance(value, bool):
            return "Sim" if value else "Não"
        return value if value is not None else "—"


def build_cruds():
    from apps.catalog.models import Category, Collection, Color, Size, SizeChart
    from apps.content.models import FAQ, Banner, Page
    from apps.personalization.models import PrintPlacement
    from apps.promotions.models import Coupon, Promotion
    from apps.shipping.models import ShippingMethod

    return [
        Crud("categorias", Category, "Categorias", "categoria", [("name", "Nome"), ("slug", "Slug"), ("is_active", "Ativa"), ("position", "Ordem")],
             fields=["name", "slug", "parent", "description", "image", "show_in_menu", "is_active", "position"],
             search=["name"], section="catalog"),
        Crud("colecoes", Collection, "Coleções", "coleção", [("name", "Nome"), ("label", "Etiqueta"), ("is_featured", "Destaque"), ("is_active", "Ativa")],
             fields=["name", "slug", "label", "tagline", "description", "cover", "accent", "is_active", "is_featured", "release_date", "position"],
             search=["name"], section="catalog"),
        Crud("cores", Color, "Cores", "cor", [("name", "Nome"), ("hex", "Hex")], fields=["name", "slug", "hex", "position"], section="catalog"),
        Crud("tamanhos", Size, "Tamanhos", "tamanho", [("name", "Tamanho"), ("position", "Ordem")], fields=["name", "position"], section="catalog"),
        Crud("tabelas-medidas", SizeChart, "Tabelas de medidas", "tabela", [("name", "Nome")], fields=["name", "headers", "rows", "note"], section="catalog"),
        Crud("cupons", Coupon, "Cupons", "cupom", [("code", "Código"), ("get_kind_display", "Tipo"), ("value", "Valor"), ("uses_count", "Usos"), ("is_active", "Ativo"), ("ends_at", "Validade")],
             form_class=CouponForm, search=["code", "description"], section="promotions", can_delete=False),
        Crud("promocoes", Promotion, "Promoções", "promoção", [("name", "Nome"), ("get_kind_display", "Tipo"), ("value", "Valor"), ("is_active", "Ativa"), ("starts_at", "Início"), ("ends_at", "Fim")],
             form_class=PromotionForm, search=["name"], section="promotions"),
        Crud("banners", Banner, "Banners", "banner", [("title", "Título"), ("get_placement_display", "Posição"), ("is_active", "Ativo"), ("position", "Ordem")],
             fields=["placement", "eyebrow", "title", "subtitle", "image", "image_mobile", "image_alt", "primary_label", "primary_url",
                     "secondary_label", "secondary_url", "is_active", "starts_at", "ends_at", "position"], section="content",
             help="O hero da homepage usa o primeiro banner ativo da posição “Hero”. Sem banner, a homepage usa os textos padrão."),
        Crud("paginas", Page, "Páginas institucionais", "página", [("title", "Título"), ("slug", "Slug"), ("is_published", "Publicada")],
             fields=["title", "slug", "body", "is_published", "show_in_footer", "position", "seo_description"], search=["title"], section="content"),
        Crud("faq", FAQ, "Perguntas frequentes", "pergunta", [("question", "Pergunta"), ("is_active", "Ativa"), ("position", "Ordem")],
             fields=["question", "answer", "position", "is_active"], section="content"),
        Crud("entregas", ShippingMethod, "Métodos de entrega", "método", [("name", "Nome"), ("get_kind_display", "Tipo"), ("price", "Valor"), ("states", "UFs"), ("is_active", "Ativo")],
             fields=["name", "kind", "is_active", "price", "free_above", "states", "cep_ranges", "days_min", "days_max", "extra_days",
                     "service_ids", "instructions", "position"], section="shipping", can_delete=False,
             help="Melhor Envio só retorna cotações quando MELHORENVIO_TOKEN e STORE_ORIGIN_ZIPCODE estão configurados. Nunca exibimos valores inventados."),
        Crud("posicoes-estampa", PrintPlacement, "Posições de estampa", "posição", [("name", "Nome"), ("get_side_display", "Lado"), ("fee", "Valor"), ("is_active", "Ativa")],
             fields=["name", "code", "side", "description", "fee", "max_width_cm", "box_left", "box_top", "box_width", "box_height", "is_active", "position"],
             section="personalization", can_delete=False),
    ]
