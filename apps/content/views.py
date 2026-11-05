from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.ratelimit import rate_limited

from .models import FAQ, NewsletterSubscriber, Page

CONSENT_TEXT = "Aceito receber e-mails sobre lançamentos e promoções. Posso cancelar a qualquer momento."


class NewsletterForm(forms.Form):
    email = forms.EmailField(label="Seu e-mail", max_length=254)
    consent = forms.BooleanField(label=CONSENT_TEXT, required=True,
                                 error_messages={"required": "Marque a caixa para confirmar seu consentimento."})
    website = forms.CharField(required=False)  # honeypot anti-spam


def page(request, slug):
    obj = get_object_or_404(Page, slug=slug, is_published=True)
    return render(request, "content/page.html", {"page": obj})


def about(request):
    return render(request, "content/about.html")


def faq(request):
    return render(request, "content/faq.html", {"faqs": FAQ.objects.filter(is_active=True)})


@require_POST
def newsletter_subscribe(request):
    form = NewsletterForm(request.POST)
    is_htmx = bool(request.headers.get("HX-Request"))
    if rate_limited(request, "newsletter", limit=10, window=3600):
        form.add_error(None, "Muitas tentativas. Tente novamente mais tarde.")
    elif form.is_valid() and not form.cleaned_data["website"]:
        email = form.cleaned_data["email"].lower()
        sub, created = NewsletterSubscriber.objects.get_or_create(
            email=email,
            defaults={"consent": True, "consent_at": timezone.now(), "consent_text": CONSENT_TEXT,
                      "source": "site", "ip_address": request.META.get("REMOTE_ADDR")},
        )
        if not created and sub.unsubscribed_at:
            sub.unsubscribed_at = None
            sub.consent_at = timezone.now()
            sub.save(update_fields=["unsubscribed_at", "consent_at", "updated_at"])
        if is_htmx:
            return render(request, "content/_newsletter_form.html", {"done": True})
        messages.success(request, "Inscrição confirmada. Valeu!")
        return redirect(request.META.get("HTTP_REFERER") or "/")
    if is_htmx:
        return render(request, "content/_newsletter_form.html", {"form": form})
    messages.error(request, "Não foi possível concluir a inscrição. Verifique o e-mail e o consentimento.")
    return redirect(request.META.get("HTTP_REFERER") or "/")


def newsletter_unsubscribe(request, token):
    sub = get_object_or_404(NewsletterSubscriber, unsubscribe_token=token)
    if request.method == "POST":
        sub.unsubscribed_at = timezone.now()
        sub.save(update_fields=["unsubscribed_at", "updated_at"])
        messages.success(request, "Pronto: você não receberá mais nossos e-mails de marketing.")
        return redirect("core:home")
    return render(request, "content/unsubscribe.html", {"sub": sub})
