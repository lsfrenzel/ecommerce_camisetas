import secrets

from django.core.cache import cache
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.core.models import TimeStampedModel

hex_color = RegexValidator(r"^#[0-9A-Fa-f]{6}$", "Use o formato #RRGGBB.")

BRAND_CACHE_KEY = "brand-settings-v1"


class BrandSettings(TimeStampedModel):
    """Configurações da marca — singleton editável no painel. Nada de identidade fixa no código."""

    store_name = models.CharField("nome da marca", max_length=80, default="NOME DA MARCA")
    slogan = models.CharField("slogan", max_length=160, default="Da quebrada pro mundo.")
    logo = models.ImageField("logotipo (tema claro)", upload_to="brand/", blank=True)
    logo_dark = models.ImageField("logotipo (tema escuro)", upload_to="brand/", blank=True)
    favicon = models.ImageField("favicon (PNG quadrado)", upload_to="brand/", blank=True)
    og_image = models.ImageField("imagem de compartilhamento (Open Graph)", upload_to="brand/", blank=True)

    accent_color = models.CharField("cor de destaque principal", max_length=7, default="#C7FF3D", validators=[hex_color])
    accent_secondary = models.CharField("cor de destaque secundária", max_length=7, default="#FF623B", validators=[hex_color])
    accent_tertiary = models.CharField("cor de destaque terciária", max_length=7, default="#355CFF", validators=[hex_color])

    announcement = models.CharField("barra de aviso", max_length=160, blank=True,
                                     default="Frete para todo o Brasil · Parcele no cartão · Pix com aprovação na hora")

    instagram_url = models.URLField("Instagram", blank=True)
    tiktok_url = models.URLField("TikTok", blank=True)
    youtube_url = models.URLField("YouTube", blank=True)
    whatsapp_number = models.CharField("WhatsApp (somente números com DDI)", max_length=20, blank=True,
                                       help_text="Ex.: 5511999999999")
    contact_email = models.EmailField("e-mail de contato", blank=True)
    contact_phone = models.CharField("telefone de contato", max_length=20, blank=True)

    company_name = models.CharField("razão social", max_length=150, blank=True)
    cnpj = models.CharField("CNPJ", max_length=18, blank=True)
    company_address = models.CharField("endereço comercial", max_length=255, blank=True)

    manifesto_title = models.CharField("título do manifesto", max_length=120,
                                       default="MAIS DO QUE UMA CAMISETA. UMA MENSAGEM.")
    manifesto_text = models.TextField("texto do manifesto", blank=True)
    manifesto_image = models.ImageField("imagem do manifesto", upload_to="brand/", blank=True)
    about_title = models.CharField("título da página sobre", max_length=120, default="Sobre a marca")
    about_text = models.TextField("texto da página sobre", blank=True)
    origin_label = models.CharField("origem da marca", max_length=80, default="Capão Redondo · Zona Sul · SP")

    personalize_title = models.CharField("título da seção personalize", max_length=120, default="CRIE A SUA")
    personalize_text = models.CharField("texto da seção personalize", max_length=255,
                                        default="Sua arte, sua frase, sua quebrada. Envie sua ideia e a gente transforma em peça.")
    personalization_requires_approval = models.BooleanField(
        "personalização exige aprovação antes do pagamento", default=True)
    personalization_min_pixels = models.PositiveIntegerField(
        "resolução mínima recomendada (lado maior, px)", default=1800)

    max_installments_display = models.PositiveSmallIntegerField("parcelas exibidas (sem juros)", default=3)
    min_installment_value = models.DecimalField("valor mínimo da parcela", max_digits=8, decimal_places=2, default=30)
    free_shipping_threshold = models.DecimalField("frete grátis acima de (informativo)", max_digits=10,
                                                  decimal_places=2, null=True, blank=True)
    seo_description = models.CharField("descrição padrão (SEO)", max_length=170, blank=True,
                                       default="Streetwear brasileiro com identidade. Camisetas oversized autorais, arte, atitude e propósito.")

    class Meta:
        verbose_name = "configurações da marca"
        verbose_name_plural = "configurações da marca"

    def __str__(self):
        return self.store_name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(BRAND_CACHE_KEY)

    @classmethod
    def load(cls) -> "BrandSettings":
        obj = cache.get(BRAND_CACHE_KEY)
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set(BRAND_CACHE_KEY, obj, 300)
        return obj

    @property
    def whatsapp_link(self) -> str:
        digits = "".join(c for c in self.whatsapp_number if c.isdigit())
        return f"https://wa.me/{digits}" if digits else ""


class Banner(TimeStampedModel):
    class Placement(models.TextChoices):
        HERO = "hero", "Hero da homepage"
        STRIP = "strip", "Faixa promocional"
        PERSONALIZE = "personalize", "Seção personalize"

    placement = models.CharField("posição", max_length=20, choices=Placement.choices, default=Placement.HERO, db_index=True)
    eyebrow = models.CharField("sobretítulo", max_length=60, blank=True)
    title = models.CharField("título", max_length=120)
    subtitle = models.CharField("subtítulo", max_length=255, blank=True)
    image = models.ImageField("imagem (desktop)", upload_to="banners/", blank=True)
    image_mobile = models.ImageField("imagem (mobile)", upload_to="banners/", blank=True)
    image_alt = models.CharField("texto alternativo", max_length=160, blank=True)
    primary_label = models.CharField("botão principal", max_length=40, blank=True)
    primary_url = models.CharField("link do botão principal", max_length=255, blank=True)
    secondary_label = models.CharField("botão secundário", max_length=40, blank=True)
    secondary_url = models.CharField("link do botão secundário", max_length=255, blank=True)
    is_active = models.BooleanField("ativo", default=True)
    starts_at = models.DateTimeField("início", null=True, blank=True)
    ends_at = models.DateTimeField("fim", null=True, blank=True)
    position = models.PositiveIntegerField("ordem", default=0)

    class Meta:
        ordering = ["placement", "position", "-created_at"]
        verbose_name = "banner"
        verbose_name_plural = "banners"

    def __str__(self):
        return self.title

    @classmethod
    def live(cls, placement):
        now = timezone.now()
        return (
            cls.objects.filter(placement=placement, is_active=True)
            .filter(models.Q(starts_at__isnull=True) | models.Q(starts_at__lte=now))
            .filter(models.Q(ends_at__isnull=True) | models.Q(ends_at__gte=now))
        )


class Page(TimeStampedModel):
    """Páginas institucionais e legais (privacidade, termos, trocas, entrega...)."""

    slug = models.SlugField(unique=True)
    title = models.CharField("título", max_length=150)
    body = models.TextField("conteúdo", help_text="Texto simples. Linhas em branco separam parágrafos; linhas iniciadas com '## ' viram subtítulos.")
    is_published = models.BooleanField("publicada", default=True)
    show_in_footer = models.BooleanField("exibir no rodapé", default=True)
    position = models.PositiveIntegerField("ordem", default=0)
    seo_description = models.CharField(max_length=170, blank=True)

    class Meta:
        ordering = ["position", "title"]
        verbose_name = "página institucional"
        verbose_name_plural = "páginas institucionais"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("content:page", args=[self.slug])


class FAQ(TimeStampedModel):
    question = models.CharField("pergunta", max_length=200)
    answer = models.TextField("resposta")
    position = models.PositiveIntegerField("ordem", default=0)
    is_active = models.BooleanField("ativa", default=True)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "pergunta frequente"
        verbose_name_plural = "perguntas frequentes"

    def __str__(self):
        return self.question


def _token():
    return secrets.token_urlsafe(24)


class NewsletterSubscriber(TimeStampedModel):
    email = models.EmailField(unique=True)
    consent = models.BooleanField("consentimento expresso", default=False)
    consent_at = models.DateTimeField(null=True, blank=True)
    consent_text = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=40, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)
    unsubscribe_token = models.CharField(max_length=64, default=_token, unique=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "inscrito na newsletter"
        verbose_name_plural = "inscritos na newsletter"
        constraints = [
            models.CheckConstraint(condition=models.Q(consent=True), name="newsletter_requires_consent"),
        ]

    def __str__(self):
        return self.email

    @property
    def is_active(self):
        return self.unsubscribed_at is None
