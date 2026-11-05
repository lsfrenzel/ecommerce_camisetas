from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.forms import PasswordChangeForm, PasswordResetForm, SetPasswordForm

from apps.core.utils import is_valid_cpf, only_digits, validate_phone

from .models import Address, DataRequest, SupportRequest, User


def style(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault("class", "checkbox")
        elif isinstance(widget, (forms.RadioSelect, forms.CheckboxSelectMultiple)):
            continue
        else:
            widget.attrs.setdefault("class", "input")
    return form


class StyledMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style(self)


class SignupForm(StyledMixin, forms.Form):
    full_name = forms.CharField(label="Nome completo", max_length=150,
                                widget=forms.TextInput(attrs={"autocomplete": "name"}))
    email = forms.EmailField(label="E-mail", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password1 = forms.CharField(label="Senha", strip=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                                help_text="Mínimo de 8 caracteres; evite senhas óbvias.")
    password2 = forms.CharField(label="Confirme a senha", strip=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    accept_terms = forms.BooleanField(label="Li e aceito os termos de uso e a política de privacidade.",
                                      error_messages={"required": "É preciso aceitar os termos para criar a conta."})
    marketing_opt_in = forms.BooleanField(label="Quero receber novidades, drops e promoções por e-mail.", required=False)
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Já existe uma conta com este e-mail. Tente entrar ou recuperar a senha.")
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "As senhas não conferem.")
        if p1:
            temp = User(email=cleaned.get("email", ""), full_name=cleaned.get("full_name", ""))
            try:
                password_validation.validate_password(p1, temp)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        if cleaned.get("website"):
            raise forms.ValidationError("Não foi possível concluir o cadastro.")
        return cleaned

    def save(self):
        d = self.cleaned_data
        user = User.objects.create_user(email=d["email"], password=d["password1"], full_name=d["full_name"].strip())
        if d.get("marketing_opt_in"):
            user.profile.set_marketing(True)
            user.profile.save()
        return user


class LoginForm(StyledMixin, forms.Form):
    email = forms.EmailField(label="E-mail", widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}))
    password = forms.CharField(label="Senha", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        email, password = cleaned.get("email"), cleaned.get("password")
        if email and password:
            self.user = authenticate(self.request, email=email, password=password)
            if self.user is None:
                raise forms.ValidationError("E-mail ou senha incorretos.")
        return cleaned


class ProfileForm(StyledMixin, forms.Form):
    full_name = forms.CharField(label="Nome completo", max_length=150)
    phone = forms.CharField(label="Celular / WhatsApp", max_length=20, required=False,
                            widget=forms.TextInput(attrs={"data-mask": "phone", "inputmode": "tel"}))
    cpf = forms.CharField(label="CPF", max_length=14, required=False,
                          widget=forms.TextInput(attrs={"data-mask": "999.999.999-99", "inputmode": "numeric"}))
    birth_date = forms.DateField(label="Data de nascimento", required=False,
                                 widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def clean_phone(self):
        phone = self.cleaned_data.get("phone", "")
        if phone:
            validate_phone(phone)
        return phone

    def clean_cpf(self):
        cpf = self.cleaned_data.get("cpf", "")
        if cpf and not is_valid_cpf(cpf):
            raise forms.ValidationError("CPF inválido.")
        return only_digits(cpf)


class PreferencesForm(StyledMixin, forms.Form):
    marketing_opt_in = forms.BooleanField(label="Receber novidades, drops e promoções por e-mail", required=False)
    order_updates_whatsapp = forms.BooleanField(label="Receber atualizações de pedidos pelo WhatsApp", required=False)


class AddressForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Address
        fields = ["label", "recipient_name", "cep", "street", "number", "complement", "neighborhood", "city", "state",
                  "is_default"]
        widgets = {
            "cep": forms.TextInput(attrs={"data-mask": "99999-999", "inputmode": "numeric", "onblur": "lookupCep(this)"}),
        }


class SupportForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = SupportRequest
        fields = ["order", "subject", "message"]
        widgets = {"message": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order"].queryset = user.orders.all() if user else self.fields["order"].queryset.none()
        self.fields["order"].required = False
        self.fields["order"].label_from_instance = lambda o: f"#{o.number} — {o.created_at:%d/%m/%Y}"


class DataRequestForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = DataRequest
        fields = ["kind", "details"]
        widgets = {"details": forms.Textarea(attrs={"rows": 4})}


class StyledPasswordChangeForm(StyledMixin, PasswordChangeForm):
    pass


class StyledPasswordResetForm(StyledMixin, PasswordResetForm):
    pass


class StyledSetPasswordForm(StyledMixin, SetPasswordForm):
    pass
