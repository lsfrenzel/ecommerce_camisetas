from decimal import Decimal

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from apps.core.models import PublicIdModel, TimeStampedModel

hex_color = RegexValidator(r"^#[0-9A-Fa-f]{6}$", "Use o formato #RRGGBB.")
POSITIVE = [MinValueValidator(Decimal("0.00"))]


def unique_slug(instance, value, field="slug"):
    base = slugify(value)[:70] or "item"
    slug, n = base, 2
    model = type(instance)
    while model.objects.filter(**{field: slug}).exclude(pk=instance.pk).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


class Category(TimeStampedModel):
    name = models.CharField("nome", max_length=80)
    slug = models.SlugField(unique=True, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="children", verbose_name="categoria pai")
    description = models.CharField("descrição", max_length=255, blank=True)
    image = models.ImageField("imagem", upload_to="categories/", blank=True)
    show_in_menu = models.BooleanField("exibir no menu", default=True)
    is_active = models.BooleanField("ativa", default=True)
    position = models.PositiveIntegerField("ordem", default=0)

    class Meta:
        ordering = ["position", "name"]
        verbose_name = "categoria"
        verbose_name_plural = "categorias"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:category", args=[self.slug])


class Collection(TimeStampedModel):
    name = models.CharField("nome", max_length=80)
    slug = models.SlugField(unique=True, blank=True)
    label = models.CharField("etiqueta", max_length=30, blank=True, help_text="Ex.: DROP 001")
    tagline = models.CharField("chamada curta", max_length=140, blank=True)
    description = models.TextField("descrição", blank=True)
    cover = models.ImageField("capa", upload_to="collections/", blank=True)
    accent = models.CharField("cor de destaque", max_length=7, default="#C7FF3D", validators=[hex_color])
    is_active = models.BooleanField("ativa", default=True)
    is_featured = models.BooleanField("destaque na homepage", default=False)
    release_date = models.DateField("lançamento", null=True, blank=True)
    position = models.PositiveIntegerField("ordem", default=0)

    class Meta:
        ordering = ["position", "-release_date", "name"]
        verbose_name = "coleção"
        verbose_name_plural = "coleções"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:collection", args=[self.slug])


class Color(models.Model):
    name = models.CharField("nome", max_length=40, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    hex = models.CharField("cor", max_length=7, default="#171717", validators=[hex_color])
    position = models.PositiveIntegerField("ordem", default=0)

    class Meta:
        ordering = ["position", "name"]
        verbose_name = "cor"
        verbose_name_plural = "cores"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        super().save(*args, **kwargs)


class Size(models.Model):
    name = models.CharField("tamanho", max_length=10, unique=True)
    position = models.PositiveIntegerField("ordem", default=0)

    class Meta:
        ordering = ["position"]
        verbose_name = "tamanho"
        verbose_name_plural = "tamanhos"

    def __str__(self):
        return self.name


class SizeChart(models.Model):
    name = models.CharField("nome", max_length=80)
    headers = models.CharField("colunas", max_length=255, default="Tamanho;Largura (cm);Comprimento (cm);Manga (cm)",
                               help_text="Separe as colunas com ponto e vírgula.")
    rows = models.TextField("linhas", help_text="Uma linha por tamanho, colunas separadas por ponto e vírgula.")
    note = models.CharField("observação", max_length=255, blank=True,
                            default="Medidas da peça aberta, podem variar em até 2 cm.")

    class Meta:
        verbose_name = "tabela de medidas"
        verbose_name_plural = "tabelas de medidas"

    def __str__(self):
        return self.name

    @property
    def header_list(self):
        return [h.strip() for h in self.headers.split(";")]

    @property
    def row_list(self):
        return [[c.strip() for c in line.split(";")] for line in self.rows.splitlines() if line.strip()]


class ProductQuerySet(models.QuerySet):
    def visible(self):
        return self.filter(status=Product.Status.ACTIVE)


class Product(PublicIdModel, TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        ACTIVE = "active", "Ativo"
        INACTIVE = "inactive", "Inativo"
        ARCHIVED = "archived", "Arquivado"

    name = models.CharField("nome", max_length=140)
    slug = models.SlugField(unique=True, blank=True, max_length=90)
    sku_base = models.CharField("SKU base", max_length=40, unique=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products", verbose_name="categoria")
    collections = models.ManyToManyField(Collection, blank=True, related_name="products", verbose_name="coleções")
    badge = models.CharField("etiqueta", max_length=30, blank=True, help_text="Ex.: NOVO, EDIÇÃO LIMITADA")

    short_description = models.CharField("resumo", max_length=255, blank=True)
    description = models.TextField("descrição", blank=True)
    fabric = models.CharField("tecido", max_length=120, blank=True)
    composition = models.CharField("composição", max_length=120, blank=True)
    fit_description = models.CharField("modelagem", max_length=160, blank=True)
    care_instructions = models.TextField("instruções de lavagem", blank=True)
    size_chart = models.ForeignKey(SizeChart, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="tabela de medidas")

    price = models.DecimalField("preço de venda", max_digits=10, decimal_places=2, validators=POSITIVE)
    compare_at_price = models.DecimalField("preço 'de' (referência)", max_digits=10, decimal_places=2,
                                           null=True, blank=True, validators=POSITIVE)
    cost_price = models.DecimalField("preço de custo", max_digits=10, decimal_places=2, default=0, validators=POSITIVE)
    sale_price = models.DecimalField("preço promocional", max_digits=10, decimal_places=2, null=True, blank=True,
                                     validators=POSITIVE)
    sale_starts_at = models.DateTimeField("promoção começa em", null=True, blank=True)
    sale_ends_at = models.DateTimeField("promoção termina em", null=True, blank=True)

    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    is_featured = models.BooleanField("destaque na homepage", default=False, db_index=True)
    is_customizable = models.BooleanField("disponível para personalização", default=False)
    sold_count = models.PositiveIntegerField("unidades vendidas", default=0, editable=False, db_index=True)

    weight_grams = models.PositiveIntegerField("peso com embalagem (g)", default=300)
    length_cm = models.PositiveIntegerField("comprimento (cm)", default=30)
    width_cm = models.PositiveIntegerField("largura (cm)", default=25)
    height_cm = models.PositiveIntegerField("altura (cm)", default=4)

    seo_title = models.CharField("título SEO", max_length=70, blank=True)
    seo_description = models.CharField("descrição SEO", max_length=170, blank=True)

    # Preparado para integrações futuras (Shopee, Mercado Livre).
    external_refs = models.JSONField("referências externas", default=dict, blank=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "produto"
        verbose_name_plural = "produtos"
        indexes = [models.Index(fields=["status", "-created_at"]), models.Index(fields=["status", "price"])]
        constraints = [
            models.CheckConstraint(condition=Q(price__gte=0), name="product_price_non_negative"),
            models.CheckConstraint(condition=Q(sale_price__isnull=True) | Q(sale_price__gte=0),
                                   name="product_sale_price_non_negative"),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        self.sku_base = self.sku_base.upper().strip()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:product", args=[self.slug])

    @property
    def is_visible(self):
        return self.status == self.Status.ACTIVE

    def sale_is_active(self, now=None) -> bool:
        if self.sale_price is None or self.sale_price >= self.price:
            return False
        now = now or timezone.now()
        if self.sale_starts_at and now < self.sale_starts_at:
            return False
        if self.sale_ends_at and now > self.sale_ends_at:
            return False
        return True

    @property
    def primary_image(self):
        images = list(self.images.all())
        return images[0] if images else None

    @property
    def secondary_image(self):
        images = list(self.images.all())
        return images[1] if len(images) > 1 else None


class ProductVariant(TimeStampedModel):
    class Fit(models.TextChoices):
        OVERSIZED = "oversized", "Oversized"
        REGULAR = "regular", "Tradicional"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    sku = models.CharField("SKU", max_length=60, unique=True)
    color = models.ForeignKey(Color, on_delete=models.PROTECT, related_name="variants", verbose_name="cor")
    size = models.ForeignKey(Size, on_delete=models.PROTECT, related_name="variants", verbose_name="tamanho")
    fit = models.CharField("modelagem", max_length=12, choices=Fit.choices, default=Fit.OVERSIZED)
    price_override = models.DecimalField("preço específico", max_digits=10, decimal_places=2, null=True, blank=True,
                                         validators=POSITIVE, help_text="Deixe vazio para usar o preço do produto.")
    stock = models.PositiveIntegerField("estoque físico", default=0)
    reserved = models.PositiveIntegerField("reservado", default=0, editable=False)
    low_stock_threshold = models.PositiveIntegerField("estoque mínimo", default=3)
    is_active = models.BooleanField("ativa", default=True)
    external_refs = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["product", "color__position", "size__position"]
        verbose_name = "variação"
        verbose_name_plural = "variações"
        constraints = [
            models.UniqueConstraint(fields=["product", "color", "size", "fit"], name="unique_variant_combo"),
            models.CheckConstraint(condition=Q(stock__gte=0), name="variant_stock_non_negative"),
            models.CheckConstraint(condition=Q(reserved__gte=0), name="variant_reserved_non_negative"),
            models.CheckConstraint(condition=Q(reserved__lte=F("stock")), name="variant_reserved_lte_stock"),
        ]
        indexes = [models.Index(fields=["product", "is_active"])]

    def __str__(self):
        return f"{self.product.name} — {self.label}"

    @property
    def label(self):
        return f"{self.get_fit_display()} / {self.color.name} / {self.size.name}"

    @property
    def available(self) -> int:
        return max(self.stock - self.reserved, 0)

    @property
    def is_low_stock(self):
        return self.available <= self.low_stock_threshold

    @property
    def base_price(self) -> Decimal:
        return self.price_override if self.price_override is not None else self.product.price

    def save(self, *args, **kwargs):
        self.sku = self.sku.upper().strip()
        super().save(*args, **kwargs)


class ProductImage(TimeStampedModel):
    class View(models.TextChoices):
        FRONT = "front", "Frente"
        BACK = "back", "Costas"
        DETAIL = "detail", "Detalhe"
        MODEL = "model", "Modelo vestindo"
        FLAT = "flat", "Still"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    color = models.ForeignKey(Color, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="cor",
                              help_text="Opcional: associa a imagem a uma cor específica.")
    image = models.ImageField("imagem", upload_to="products/%Y/%m/", width_field="width", height_field="height")
    thumbnail = models.ImageField("miniatura", upload_to="products/thumbs/%Y/%m/", blank=True, editable=False)
    width = models.PositiveIntegerField(null=True, editable=False)
    height = models.PositiveIntegerField(null=True, editable=False)
    alt = models.CharField("texto alternativo", max_length=160, blank=True)
    view = models.CharField("vista", max_length=10, choices=View.choices, default=View.FRONT)
    is_illustrative = models.BooleanField("imagem ilustrativa", default=False)
    position = models.PositiveIntegerField("ordem", default=0)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "imagem de produto"
        verbose_name_plural = "imagens de produto"

    def __str__(self):
        return self.alt or f"Imagem de {self.product}"

    @property
    def thumb_url(self):
        return (self.thumbnail or self.image).url

    @property
    def alt_text(self):
        return self.alt or f"{self.product.name} — {self.get_view_display().lower()}"
