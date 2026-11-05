from django.contrib import messages
from django.shortcuts import redirect, render

from apps.content.models import BrandSettings
from apps.core.audit import log_action
from apps.core.models import AuditLog

from .forms import StyledModelForm
from .permissions import staff_required


class BrandForm(StyledModelForm):
    class Meta:
        model = BrandSettings
        exclude = ["created_at", "updated_at"]


@staff_required("content.view_brandsettings")
def brand_settings(request):
    brand = BrandSettings.load()
    brand = BrandSettings.objects.get(pk=brand.pk)
    form = BrandForm(request.POST or None, request.FILES or None, instance=brand)
    if request.method == "POST":
        if not request.user.has_perm("content.change_brandsettings"):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied
        if form.is_valid():
            changed = list(form.changed_data)
            form.save()
            log_action(actor=request.user, action=AuditLog.Action.SETTINGS, obj=brand, request=request,
                       message="Campos: " + ", ".join(changed)[:200])
            messages.success(request, "Configurações da marca salvas.")
            return redirect("dashboard:brand")
    groups = [
        ("Identidade", ["store_name", "slogan", "logo", "logo_dark", "favicon", "og_image", "accent_color",
                        "accent_secondary", "accent_tertiary", "announcement", "origin_label"]),
        ("Contato e redes", ["instagram_url", "tiktok_url", "youtube_url", "whatsapp_number", "contact_email", "contact_phone"]),
        ("Dados comerciais", ["company_name", "cnpj", "company_address"]),
        ("Textos institucionais", ["manifesto_title", "manifesto_text", "manifesto_image", "about_title", "about_text", "seo_description"]),
        ("Personalização", ["personalize_title", "personalize_text", "personalization_requires_approval", "personalization_min_pixels"]),
        ("Vendas", ["max_installments_display", "min_installment_value", "free_shipping_threshold"]),
    ]
    return render(request, "dashboard/brand.html", {
        "form": form, "groups": [(title, [form[f] for f in fields]) for title, fields in groups], "section": "brand"})
