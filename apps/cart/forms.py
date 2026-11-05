from django import forms

from apps.core.utils import UF_CHOICES, format_cep, is_valid_cpf, only_digits, validate_cep, validate_phone
from apps.orders.services import CheckoutData, normalize_phone


class CheckoutForm(forms.Form):
    email = forms.EmailField(label="E-mail", max_length=254)
    full_name = forms.CharField(label="Nome completo", max_length=150)
    phone = forms.CharField(label="Celular / WhatsApp", max_length=20, validators=[validate_phone])
    cpf = forms.CharField(label="CPF", max_length=14, required=False,
                          help_text="Opcional aqui; pode ser solicitado pelo Mercado Pago para Pix/cartão e para emissão de nota fiscal.")
    cep = forms.CharField(label="CEP", max_length=9, validators=[validate_cep])
    street = forms.CharField(label="Endereço", max_length=200)
    number = forms.CharField(label="Número", max_length=20)
    complement = forms.CharField(label="Complemento", max_length=100, required=False)
    neighborhood = forms.CharField(label="Bairro", max_length=100)
    city = forms.CharField(label="Cidade", max_length=100)
    state = forms.ChoiceField(label="UF", choices=[("", "UF")] + UF_CHOICES)
    shipping_code = forms.CharField(label="Entrega", max_length=40,
                                    error_messages={"required": "Escolha uma opção de entrega."})
    notes = forms.CharField(label="Observações do pedido", required=False, max_length=1000,
                            widget=forms.Textarea(attrs={"rows": 2}))
    accept_terms = forms.BooleanField(
        label="Li e aceito os termos de compra e a política de trocas.",
        error_messages={"required": "É preciso aceitar os termos de compra para continuar."})
    marketing_opt_in = forms.BooleanField(label="Quero receber novidades e promoções por e-mail.", required=False)
    save_address = forms.BooleanField(label="Salvar este endereço na minha conta", required=False, initial=True)

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if not (user and user.is_authenticated):
            self.fields.pop("save_address")
        attrs = {
            "email": {"autocomplete": "email", "inputmode": "email"},
            "full_name": {"autocomplete": "name"},
            "phone": {"autocomplete": "tel", "inputmode": "tel", "data-mask": "phone"},
            "cpf": {"inputmode": "numeric", "data-mask": "999.999.999-99"},
            "cep": {"autocomplete": "postal-code", "inputmode": "numeric", "data-mask": "99999-999",
                    "onblur": "lookupCep(this)"},
            "street": {"autocomplete": "address-line1"},
            "number": {"inputmode": "numeric"},
            "complement": {"autocomplete": "address-line2"},
            "neighborhood": {"autocomplete": "address-level3"},
            "city": {"autocomplete": "address-level2"},
            "state": {"autocomplete": "address-level1"},
        }
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "checkbox"
            elif name != "shipping_code":
                field.widget.attrs["class"] = "input"
            field.widget.attrs.update(attrs.get(name, {}))

    def clean_cpf(self):
        cpf = self.cleaned_data.get("cpf", "")
        if cpf and not is_valid_cpf(cpf):
            raise forms.ValidationError("CPF inválido.")
        return only_digits(cpf)

    def clean_cep(self):
        return format_cep(self.cleaned_data["cep"])

    def clean_phone(self):
        return normalize_phone(self.cleaned_data["phone"])

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def to_checkout_data(self) -> CheckoutData:
        d = self.cleaned_data
        return CheckoutData(
            email=d["email"], full_name=d["full_name"], phone=d["phone"], cpf=d.get("cpf", ""), cep=d["cep"],
            street=d["street"], number=d["number"], complement=d.get("complement", ""),
            neighborhood=d["neighborhood"], city=d["city"], state=d["state"], shipping_code=d["shipping_code"],
            notes=d.get("notes", ""),
        )

    def save_to_profile(self, user):
        if not (user and user.is_authenticated):
            return
        d = self.cleaned_data
        profile = user.profile
        changed = []
        if d.get("phone") and not profile.phone:
            profile.phone = d["phone"]
            changed.append("phone")
        if d.get("cpf") and not profile.cpf:
            profile.cpf = d["cpf"]
            changed.append("cpf")
        if d.get("marketing_opt_in") and not profile.marketing_opt_in:
            profile.set_marketing(True)
            changed += ["marketing_opt_in", "marketing_opt_in_at"]
        if changed:
            profile.save(update_fields=changed + ["updated_at"])
        if d.get("save_address"):
            from apps.accounts.models import Address

            exists = user.addresses.filter(cep=d["cep"], number=d["number"], street=d["street"]).exists()
            if not exists:
                Address.objects.create(
                    user=user, recipient_name=d["full_name"], cep=d["cep"], street=d["street"], number=d["number"],
                    complement=d.get("complement", ""), neighborhood=d["neighborhood"], city=d["city"],
                    state=d["state"], is_default=not user.addresses.exists(),
                )
