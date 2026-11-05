import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.core.audit import log_action
from apps.core.models import AuditLog
from apps.core.ratelimit import is_blocked, rate_limited, reset
from apps.orders.models import Order

from .forms import (AddressForm, DataRequestForm, LoginForm, PreferencesForm, ProfileForm, SignupForm,
                    StyledPasswordChangeForm, StyledPasswordResetForm, StyledSetPasswordForm, SupportForm)
from .models import Address


def _safe_next(request, default="accounts:dashboard"):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()):
        return nxt
    return default


def _claim_guest_orders(request, user):
    """Vincula à nova conta apenas os pedidos de visitante feitos nesta mesma sessão e com o mesmo e-mail."""
    ids = request.session.get("guest_orders", [])
    if ids:
        Order.objects.filter(public_id__in=ids, user__isnull=True, email__iexact=user.email).update(user=user)


def signup(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    form = SignupForm(request.POST or None, initial={"email": request.GET.get("email", "")})
    if request.method == "POST":
        if rate_limited(request, "signup", limit=8, window=3600):
            form.add_error(None, "Muitas tentativas. Tente novamente mais tarde.")
        elif form.is_valid():
            user = form.save()
            guest_ids = request.session.get("guest_orders", [])
            login(request, user, backend="apps.accounts.backends.EmailBackend")
            request.session["guest_orders"] = guest_ids
            _claim_guest_orders(request, user)
            messages.success(request, f"Conta criada. Bem-vindo(a), {user.get_short_name()}!")
            return redirect(_safe_next(request))
    return render(request, "accounts/signup.html", {"form": form, "next": request.GET.get("next", "")})


def login_view(request):
    if request.user.is_authenticated:
        return redirect(_safe_next(request))
    form = LoginForm(request, request.POST or None)
    limit = settings.LOGIN_RATE_LIMIT_ATTEMPTS
    window = settings.LOGIN_RATE_LIMIT_WINDOW
    if request.method == "POST":
        email_key = (request.POST.get("email") or "").strip().lower()[:254]
        if is_blocked(request, "login-ip", limit=limit * 4) or is_blocked(request, "login-email", limit=limit, key=email_key):
            form = LoginForm(request, None)
            form.data = request.POST
            messages.error(request, "Muitas tentativas de login. Aguarde alguns minutos ou recupere sua senha.")
        elif form.is_valid():
            reset(request, "login-email", key=email_key)
            guest_ids = request.session.get("guest_orders", [])
            login(request, form.user, backend="apps.accounts.backends.EmailBackend")
            request.session["guest_orders"] = guest_ids
            _claim_guest_orders(request, form.user)
            if form.user.is_staff and not request.POST.get("next"):
                return redirect("dashboard:home")
            return redirect(_safe_next(request))
        else:
            rate_limited(request, "login-ip", limit=limit * 4, window=window)
            rate_limited(request, "login-email", limit=limit, window=window, key=email_key)
    return render(request, "accounts/login.html", {"form": form, "next": request.GET.get("next", "")})


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, "Você saiu da sua conta.")
    return redirect("core:home")


class PasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset.html"
    email_template_name = "emails/password_reset.txt"
    html_email_template_name = "emails/password_reset.html"
    subject_template_name = "emails/password_reset_subject.txt"
    form_class = StyledPasswordResetForm
    success_url = reverse_lazy("accounts:password_reset_done")

    def post(self, request, *args, **kwargs):
        if rate_limited(request, "pwreset", limit=5, window=3600):
            messages.error(request, "Muitas solicitações. Tente novamente mais tarde.")
            return redirect("accounts:password_reset")
        return super().post(request, *args, **kwargs)

    def get_extra_email_context(self):
        from apps.content.models import BrandSettings

        return {"brand": BrandSettings.load(), "site_url": settings.SITE_URL}


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    form_class = StyledSetPasswordForm
    success_url = reverse_lazy("accounts:password_reset_complete")


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


@login_required
def dashboard(request):
    orders = request.user.orders.order_by("-created_at")[:3]
    return render(request, "accounts/dashboard.html", {"orders": orders, "section": "dashboard"})


@login_required
def account_orders(request):
    orders = request.user.orders.prefetch_related("items").order_by("-created_at")
    return render(request, "orders/list.html", {"orders": orders, "section": "orders"})


@login_required
def profile(request):
    user, prof = request.user, request.user.profile
    form = ProfileForm(request.POST or None, initial={
        "full_name": user.full_name, "phone": prof.phone, "cpf": prof.cpf, "birth_date": prof.birth_date})
    if request.method == "POST" and form.is_valid():
        user.full_name = form.cleaned_data["full_name"]
        user.save(update_fields=["full_name"])
        prof.phone = form.cleaned_data["phone"]
        prof.cpf = form.cleaned_data["cpf"]
        prof.birth_date = form.cleaned_data["birth_date"]
        prof.save()
        messages.success(request, "Dados atualizados.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form, "section": "profile"})


@login_required
def preferences(request):
    prof = request.user.profile
    form = PreferencesForm(request.POST or None, initial={
        "marketing_opt_in": prof.marketing_opt_in, "order_updates_whatsapp": prof.order_updates_whatsapp})
    if request.method == "POST" and form.is_valid():
        prof.set_marketing(form.cleaned_data["marketing_opt_in"])
        prof.order_updates_whatsapp = form.cleaned_data["order_updates_whatsapp"]
        prof.save()
        if not prof.marketing_opt_in:
            from apps.content.models import NewsletterSubscriber

            NewsletterSubscriber.objects.filter(email__iexact=request.user.email, unsubscribed_at__isnull=True
                                                ).update(unsubscribed_at=timezone.now())
        messages.success(request, "Preferências salvas.")
        return redirect("accounts:preferences")
    return render(request, "accounts/preferences.html", {"form": form, "section": "preferences"})


@login_required
def addresses(request):
    return render(request, "accounts/addresses.html", {"addresses": request.user.addresses.all(), "section": "addresses"})


@login_required
def address_edit(request, pk=None):
    instance = get_object_or_404(Address, pk=pk, user=request.user) if pk else None
    form = AddressForm(request.POST or None, instance=instance,
                       initial=None if instance else {"recipient_name": request.user.full_name})
    if request.method == "POST" and form.is_valid():
        address = form.save(commit=False)
        address.user = request.user
        if not request.user.addresses.exclude(pk=address.pk).exists():
            address.is_default = True
        address.save()
        messages.success(request, "Endereço salvo.")
        return redirect("accounts:addresses")
    return render(request, "accounts/address_form.html", {"form": form, "section": "addresses", "instance": instance})


@login_required
@require_POST
def address_delete(request, pk):
    address = get_object_or_404(Address, pk=pk, user=request.user)
    address.delete()
    messages.info(request, "Endereço removido.")
    return redirect("accounts:addresses")


@login_required
def password_change(request):
    form = StyledPasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "Senha alterada.")
        return redirect("accounts:dashboard")
    return render(request, "accounts/password_change.html", {"form": form, "section": "password"})


@login_required
def support(request):
    initial = {}
    number = request.GET.get("pedido")
    if number:
        order = request.user.orders.filter(number=number).first()
        if order:
            initial["order"] = order
    form = SupportForm(request.POST or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        ticket = form.save(commit=False)
        ticket.user = request.user
        ticket.save()
        messages.success(request, "Solicitação enviada. Responderemos em breve.")
        return redirect("accounts:support")
    return render(request, "accounts/support.html", {
        "form": form, "tickets": request.user.support_requests.select_related("order"), "section": "support"})


def privacy(request):
    """Central de privacidade (LGPD): exportação e solicitações do titular."""
    if not request.user.is_authenticated:
        return render(request, "accounts/privacy_public.html")
    form = DataRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        req = form.save(commit=False)
        req.user = request.user
        req.email = request.user.email
        req.save()
        log_action(actor=request.user, action=AuditLog.Action.DATA_REQUEST, obj=req, request=request,
                   message=req.get_kind_display())
        messages.success(request, "Solicitação registrada. Responderemos no prazo legal.")
        return redirect("accounts:privacy")
    return render(request, "accounts/privacy.html", {
        "form": form, "requests": request.user.data_requests.all(), "section": "privacy"})


@login_required
def export_data(request):
    """Exporta os dados pessoais do titular em JSON (LGPD, art. 18, II e V)."""
    user = request.user
    prof = user.profile
    data = {
        "gerado_em": timezone.now().isoformat(),
        "conta": {"nome": user.full_name, "email": user.email, "criada_em": user.date_joined.isoformat()},
        "perfil": {"telefone": prof.phone, "cpf": prof.cpf,
                   "nascimento": prof.birth_date.isoformat() if prof.birth_date else None,
                   "marketing": prof.marketing_opt_in,
                   "marketing_consentido_em": prof.marketing_opt_in_at.isoformat() if prof.marketing_opt_in_at else None},
        "enderecos": [{"cep": a.cep, "endereco": a.street, "numero": a.number, "complemento": a.complement,
                       "bairro": a.neighborhood, "cidade": a.city, "uf": a.state} for a in user.addresses.all()],
        "pedidos": [{"numero": o.number, "data": o.created_at.isoformat(), "status": o.get_status_display(),
                     "total": str(o.total),
                     "itens": [{"produto": i.product_name, "variacao": i.variant_label, "qtd": i.quantity,
                                "valor": str(i.line_total)} for i in o.items.all()]}
                    for o in user.orders.prefetch_related("items")],
    }
    response = HttpResponse(json.dumps(data, ensure_ascii=False, indent=2), content_type="application/json")
    response["Content-Disposition"] = 'attachment; filename="meus-dados.json"'
    return response
