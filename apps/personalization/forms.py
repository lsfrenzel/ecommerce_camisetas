from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

from apps.accounts.forms import style
from apps.catalog.models import Product, ProductVariant
from apps.core.images import validate_and_process_upload
from apps.core.utils import validate_phone

from .models import PersonalizationRequest, PrintPlacement


class PersonalizationForm(forms.ModelForm):
    image_upload = forms.FileField(
        label="Sua arte (PNG, JPEG ou WebP)", required=False,
        widget=forms.ClearableFileInput(attrs={"accept": "image/png,image/jpeg,image/webp"}),
        help_text=f"Até {settings.PERSONALIZATION_MAX_UPLOAD_MB} MB. Para melhor qualidade, envie arte com no mínimo 1800 px no lado maior (fundo transparente em PNG é ideal).",
    )
    rights_confirmed = forms.BooleanField(
        label="Declaro que tenho os direitos de uso da imagem/texto enviados e que o conteúdo não viola direitos de terceiros.",
        error_messages={"required": "Confirme que possui os direitos sobre a arte."})

    class Meta:
        model = PersonalizationRequest
        fields = ["product", "variant", "quantity", "placement", "custom_text", "text_color", "instructions", "name",
                  "email", "phone"]
        widgets = {
            "instructions": forms.Textarea(attrs={"rows": 3, "placeholder": "Ex.: centralizar a arte, manter as cores originais…"}),
            "text_color": forms.TextInput(attrs={"type": "color"}),
            "quantity": forms.NumberInput(attrs={"min": 1, "max": 50}),
            "phone": forms.TextInput(attrs={"data-mask": "phone", "inputmode": "tel"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.processed = None
        products = Product.objects.visible().filter(is_customizable=True)
        self.fields["product"].queryset = products
        self.fields["variant"].queryset = ProductVariant.objects.filter(product__in=products, is_active=True
                                                                        ).select_related("color", "size")
        self.fields["placement"].queryset = PrintPlacement.objects.filter(is_active=True)
        self.fields["text_color"].required = False
        if user and user.is_authenticated:
            self.fields["name"].initial = user.full_name
            self.fields["email"].initial = user.email
            self.fields["phone"].initial = getattr(user.profile, "phone", "")
        style(self)

    def clean_quantity(self):
        q = self.cleaned_data["quantity"]
        if not 1 <= q <= 50:
            raise ValidationError("Quantidade entre 1 e 50. Para pedidos maiores (uniformes/corporativo), fale conosco.")
        return q

    def clean_phone(self):
        phone = self.cleaned_data.get("phone", "")
        if phone:
            validate_phone(phone)
        return phone

    def clean_text_color(self):
        import re

        color = (self.cleaned_data.get("text_color") or "").strip()
        if color and not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            raise ValidationError("Cor inválida.")
        return color

    def clean_image_upload(self):
        uploaded = self.cleaned_data.get("image_upload")
        if uploaded:
            self.processed = validate_and_process_upload(uploaded, max_mb=settings.PERSONALIZATION_MAX_UPLOAD_MB)
            self._original_name = uploaded.name[:200]
        return uploaded

    def clean(self):
        cleaned = super().clean()
        product, variant = cleaned.get("product"), cleaned.get("variant")
        if product and variant and variant.product_id != product.pk:
            self.add_error("variant", "Escolha cor e tamanho do modelo selecionado.")
        if variant and cleaned.get("quantity") and variant.available < cleaned["quantity"]:
            self.add_error("variant", f"Só temos {variant.available} unidade(s) desta base no momento.")
        if not cleaned.get("image_upload") and not cleaned.get("custom_text"):
            raise ValidationError("Envie uma imagem ou escreva um texto para personalizar.")
        return cleaned
