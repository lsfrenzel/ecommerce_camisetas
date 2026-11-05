from decimal import Decimal

from django import forms
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory

from apps.accounts.forms import style
from apps.accounts.models import User
from apps.catalog.models import Product, ProductImage, ProductVariant
from apps.core.images import make_web_versions, validate_and_process_upload
from apps.inventory.models import InventoryMovement
from apps.orders.models import OrderStatus
from apps.promotions.models import Coupon, Promotion
from apps.shipping.models import Shipment

from .permissions import ROLE_PERMISSIONS

DATETIME_WIDGET = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field, forms.DateTimeField):
                field.widget = DATETIME_WIDGET
                field.input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"]
            if isinstance(field.widget, forms.SelectMultiple):
                field.widget.attrs.setdefault("size", 6)
        style(self)


class ProductForm(StyledModelForm):
    class Meta:
        model = Product
        fields = [
            "name", "slug", "sku_base", "category", "collections", "badge", "status", "is_featured", "is_customizable",
            "short_description", "description", "fabric", "composition", "fit_description", "care_instructions",
            "size_chart", "price", "compare_at_price", "cost_price", "sale_price", "sale_starts_at", "sale_ends_at",
            "weight_grams", "length_cm", "width_cm", "height_cm", "seo_title", "seo_description",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
            "care_instructions": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["slug"].help_text = "Gerado automaticamente a partir do nome se ficar vazio."

    def clean(self):
        cleaned = super().clean()
        price, sale = cleaned.get("price"), cleaned.get("sale_price")
        if sale is not None and price is not None and sale >= price:
            self.add_error("sale_price", "O preço promocional deve ser menor que o preço de venda.")
        s, e = cleaned.get("sale_starts_at"), cleaned.get("sale_ends_at")
        if s and e and e <= s:
            self.add_error("sale_ends_at", "O fim deve ser posterior ao início.")
        return cleaned


class VariantForm(StyledModelForm):
    class Meta:
        model = ProductVariant
        fields = ["color", "size", "fit", "sku", "price_override", "low_stock_threshold", "is_active"]


class VariantFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        seen = set()
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            key = (form.cleaned_data.get("color"), form.cleaned_data.get("size"), form.cleaned_data.get("fit"))
            if key in seen:
                raise ValidationError("Há variações repetidas (mesma cor, tamanho e modelagem).")
            seen.add(key)


class ProductImageForm(StyledModelForm):
    class Meta:
        model = ProductImage
        fields = ["image", "view", "color", "alt", "position", "is_illustrative"]

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image and hasattr(image, "content_type"):  # novo upload
            processed = validate_and_process_upload(image, max_mb=settings.PRODUCT_IMAGE_MAX_UPLOAD_MB)
            self._processed = processed
        return image

    def save(self, commit=True):
        obj = super().save(commit=False)
        processed = getattr(self, "_processed", None)
        if processed is not None:
            main, _size, thumb = make_web_versions(processed.content)
            obj.image.save(main.name, main, save=False)
            obj.thumbnail.save(thumb.name, thumb, save=False)
        if commit:
            obj.save()
        return obj


ProductVariantInline = inlineformset_factory(Product, ProductVariant, form=VariantForm, formset=VariantFormSet,
                                             extra=1, can_delete=False)
ProductImageInline = inlineformset_factory(Product, ProductImage, form=ProductImageForm, extra=2, can_delete=True)


class GenerateVariantsForm(forms.Form):
    from apps.catalog.models import Color, Size

    colors = forms.ModelMultipleChoiceField(queryset=Color.objects.all(), label="Cores",
                                            widget=forms.CheckboxSelectMultiple)
    sizes = forms.ModelMultipleChoiceField(queryset=Size.objects.all(), label="Tamanhos",
                                           widget=forms.CheckboxSelectMultiple)
    fit = forms.ChoiceField(choices=ProductVariant.Fit.choices, label="Modelagem")
    initial_stock = forms.IntegerField(min_value=0, initial=0, label="Estoque inicial por variação")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style(self)


class BulkPriceForm(forms.Form):
    MODE = [("set", "Definir preço fixo"), ("percent", "Ajustar em %"), ("amount", "Somar/subtrair valor (R$)")]
    products = forms.ModelMultipleChoiceField(queryset=Product.objects.exclude(status="archived"), label="Produtos",
                                              widget=forms.CheckboxSelectMultiple)
    mode = forms.ChoiceField(choices=MODE, label="Tipo de alteração")
    value = forms.DecimalField(max_digits=10, decimal_places=2, label="Valor",
                               help_text="Ex.: 10 = +10% / -15 = -15%.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style(self)

    def new_price(self, current: Decimal) -> Decimal:
        mode, value = self.cleaned_data["mode"], self.cleaned_data["value"]
        if mode == "set":
            result = value
        elif mode == "percent":
            result = current * (Decimal("100") + value) / Decimal("100")
        else:
            result = current + value
        return result.quantize(Decimal("0.01"))

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        for p in cleaned.get("products", []):
            np = self.new_price(p.price)
            if np <= 0:
                raise ValidationError(f"O novo preço de “{p.name}” ficaria inválido ({np}).")
        return cleaned


class MovementForm(forms.Form):
    variant = forms.ModelChoiceField(
        queryset=ProductVariant.objects.select_related("product", "color", "size").order_by("product__name", "sku"),
        label="Variação (SKU)")
    kind = forms.ChoiceField(label="Tipo", choices=[
        (InventoryMovement.Kind.ENTRY, "Entrada de mercadoria"),
        (InventoryMovement.Kind.EXIT, "Saída manual"),
        (InventoryMovement.Kind.LOSS, "Perda / avaria"),
        (InventoryMovement.Kind.ADJUSTMENT, "Ajuste (+/−)"),
    ])
    quantity = forms.IntegerField(label="Quantidade", help_text="Em ajustes use negativo para reduzir.")
    unit_cost = forms.DecimalField(label="Custo unitário (entradas)", required=False, max_digits=10, decimal_places=2)
    reason = forms.CharField(label="Motivo / referência", max_length=255)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["variant"].label_from_instance = lambda v: f"{v.sku} — {v.product.name} ({v.color.name}/{v.size.name}) · disp. {v.available}"
        style(self)


class OrderStatusForm(forms.Form):
    status = forms.ChoiceField(label="Novo status")
    note = forms.CharField(label="Observação", required=False, max_length=255)
    notify = forms.BooleanField(label="Notificar cliente por e-mail", required=False, initial=True)

    def __init__(self, *args, order=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [(s, OrderStatus(s).label) for s in (order.allowed_next_statuses() if order else [])]
        self.fields["status"].choices = choices
        style(self)


class ShipmentForm(StyledModelForm):
    class Meta:
        model = Shipment
        fields = ["carrier", "service", "tracking_code", "tracking_url", "status", "posted_at", "delivered_at", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class CouponForm(StyledModelForm):
    class Meta:
        model = Coupon
        fields = ["code", "description", "kind", "value", "max_discount", "min_order_value", "max_uses",
                  "max_uses_per_customer", "starts_at", "ends_at", "is_active", "stackable_with_promotions",
                  "first_order_only", "products", "categories"]


class PromotionForm(StyledModelForm):
    class Meta:
        model = Promotion
        fields = ["name", "label", "kind", "value", "applies_to_all", "products", "categories", "collections",
                  "starts_at", "ends_at", "is_active"]

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("applies_to_all") and not (cleaned.get("products") or cleaned.get("categories")
                                                      or cleaned.get("collections")):
            raise ValidationError("Escolha produtos, categorias ou coleções — ou marque “aplicar a toda a loja”.")
        return cleaned


class StaffUserForm(forms.Form):
    full_name = forms.CharField(label="Nome", max_length=150)
    email = forms.EmailField(label="E-mail")
    role = forms.ChoiceField(label="Papel", choices=[(r, r) for r in ROLE_PERMISSIONS])
    password = forms.CharField(label="Senha inicial", widget=forms.PasswordInput, min_length=10,
                               help_text="Mínimo de 10 caracteres. Peça para a pessoa trocar no primeiro acesso.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style(self)

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("Já existe um usuário com este e-mail. Edite o papel dele na lista.")
        return email

    def clean_password(self):
        from django.contrib.auth import password_validation

        pwd = self.cleaned_data["password"]
        password_validation.validate_password(pwd)
        return pwd


class UserDataForm(forms.Form):
    """Dados cadastrais de um usuário, editados pela equipe (a senha nunca é definida por aqui)."""

    full_name = forms.CharField(label="Nome completo", max_length=150)
    email = forms.EmailField(label="E-mail de acesso")
    phone = forms.CharField(label="Telefone / WhatsApp", max_length=20, required=False)
    cpf = forms.CharField(label="CPF", max_length=14, required=False)
    birth_date = forms.DateField(label="Data de nascimento", required=False,
                                 widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)
        self.fields["phone"].widget.attrs.update({"data-mask": "phone", "inputmode": "tel"})
        self.fields["cpf"].widget.attrs.update({"data-mask": "999.999.999-99", "inputmode": "numeric"})
        style(self)

    @classmethod
    def initial_for(cls, user):
        p = user.profile
        return {"full_name": user.full_name, "email": user.email, "phone": p.phone, "cpf": p.cpf,
                "birth_date": p.birth_date}

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        qs = User.objects.filter(email__iexact=email)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Já existe outro usuário com este e-mail.")
        return email

    def clean_phone(self):
        from apps.core.utils import validate_phone

        phone = self.cleaned_data.get("phone", "")
        if phone:
            validate_phone(phone)
        return phone

    def clean_cpf(self):
        from apps.core.utils import is_valid_cpf, only_digits

        cpf = self.cleaned_data.get("cpf", "")
        if cpf and not is_valid_cpf(cpf):
            raise ValidationError("CPF inválido.")
        return only_digits(cpf)

    def apply(self, user):
        """Grava os dados e devolve as alterações para auditoria (CPF mascarado)."""
        d = self.cleaned_data
        p = user.profile
        before = {"full_name": user.full_name, "email": user.email, "phone": p.phone, "cpf": p.cpf,
                  "birth_date": p.birth_date}
        user.full_name, user.email = d["full_name"].strip(), d["email"]
        p.phone, p.cpf, p.birth_date = d["phone"], d["cpf"], d["birth_date"]
        user.save()
        p.save()
        changes = {}
        for key, old in before.items():
            new = d[key] if key not in ("full_name",) else user.full_name
            if (old or "") != (new or ""):
                changes[key] = ["***", "***"] if key == "cpf" else [old, new]
        return changes


class RoleAssignForm(forms.Form):
    role = forms.ChoiceField(label="Papel", choices=[("", "— Sem acesso ao painel (cliente) —")] + [(r, r) for r in ROLE_PERMISSIONS],
                             required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style(self)


def role_of(user) -> str:
    if user.is_superuser:
        return "Superusuário"
    names = set(user.groups.values_list("name", flat=True)) & set(ROLE_PERMISSIONS)
    return ", ".join(sorted(names)) or ("Equipe (sem papel)" if user.is_staff else "Cliente")


def ensure_groups():
    """Cria/atualiza os grupos de papéis com as permissões definidas."""
    from django.contrib.auth.models import Permission

    for name, perms in ROLE_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=name)
        if perms == "__all__":
            group.permissions.set(Permission.objects.filter(content_type__app_label__in=[
                "accounts", "catalog", "inventory", "orders", "payments", "promotions", "shipping", "content",
                "personalization", "cart", "core", "auth"]))
        else:
            objs = []
            for code in perms:
                app_label, codename = code.split(".")
                p = Permission.objects.filter(content_type__app_label=app_label, codename=codename).first()
                if p:
                    objs.append(p)
            group.permissions.set(objs)
