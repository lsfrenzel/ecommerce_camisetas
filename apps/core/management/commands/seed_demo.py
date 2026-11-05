"""
Popula o banco de DESENVOLVIMENTO com dados de exemplo editáveis no painel.

- Não cria pedidos nem pagamentos (relatórios ficam zerados até existirem vendas reais).
- As imagens são placeholders gerados (silhueta de camiseta), marcados como "ilustrativos".
  Substitua pelas fotos reais no painel → Produtos.
"""

import io
from decimal import Decimal

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from PIL import Image, ImageDraw, ImageFont

from apps.catalog.models import Category, Collection, Color, Product, ProductImage, ProductVariant, Size, SizeChart
from apps.content.models import FAQ, BrandSettings, Page
from apps.core.images import make_web_versions
from apps.inventory.models import InventoryMovement
from apps.inventory.services import record_movement
from apps.personalization.models import PrintPlacement
from apps.promotions.models import Coupon
from apps.shipping.models import ShippingMethod

W, H = 1200, 1500
SHIRT = [(430, 230), (770, 230), (1030, 340), (1130, 660), (950, 730), (895, 590), (900, 1330), (300, 1330),
         (305, 590), (250, 730), (70, 660), (170, 340)]


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow antigo
        return ImageFont.load_default()


def shirt_image(fill, *, side="front", label="", chest_text="", art=False, bg="#E9E6DF"):
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    shade = tuple(max(0, int(c * 0.86)) for c in Image.new("RGB", (1, 1), fill).getpixel((0, 0)))
    d.polygon(SHIRT, fill=fill)
    # sombras/dobras sutis
    if side == "front":
        d.ellipse([(500, 175), (700, 300)], fill=bg)
        d.arc([(500, 175), (700, 300)], 0, 180, fill=shade, width=14)
    else:
        d.arc([(500, 200), (700, 260)], 0, 180, fill=shade, width=10)
    ink = "#171717" if sum(Image.new("RGB", (1, 1), fill).getpixel((0, 0))) > 380 else "#F5F5F5"
    if chest_text:
        d.text((640, 430), chest_text, fill=ink, font=_font(22))
    if art:
        # Moldura tracejada indicando a área da arte principal (NÃO é a arte final).
        x0, y0, x1, y1 = 400, 430, 800, 980
        for x in range(x0, x1, 28):
            d.line([(x, y0), (min(x + 14, x1), y0)], fill="#FF623B", width=4)
            d.line([(x, y1), (min(x + 14, x1), y1)], fill="#FF623B", width=4)
        for y in range(y0, y1, 28):
            d.line([(x0, y), (x0, min(y + 14, y1))], fill="#FF623B", width=4)
            d.line([(x1, y), (x1, min(y + 14, y1))], fill="#FF623B", width=4)
        for (cx, cy, dx, dy) in [(x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)]:
            d.line([(cx, cy), (cx + 60 * dx, cy)], fill="#C7FF3D" if ink == "#F5F5F5" else "#355CFF", width=10)
            d.line([(cx, cy), (cx, cy + 60 * dy)], fill="#C7FF3D" if ink == "#F5F5F5" else "#355CFF", width=10)
        d.text((x0 + 40, (y0 + y1) // 2 - 40), "ARTE PRINCIPAL", fill=ink, font=_font(44))
        d.text((x0 + 40, (y0 + y1) // 2 + 20), "estampa colorida nas costas", fill=ink, font=_font(26))
    d.text((60, 50), "IMAGEM ILUSTRATIVA", fill="#5C5C58", font=_font(24))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


def poster_image(title, subtitle):
    img = Image.new("RGB", (1600, 1000), "#101010")
    d = ImageDraw.Draw(img)
    for x in range(0, 1600, 48):
        d.line([(x, 0), (x, 1000)], fill="#1F1F1F")
    for y in range(0, 1000, 48):
        d.line([(0, y), (1600, y)], fill="#1F1F1F")
    d.rectangle([(80, 80), (360, 130)], fill="#C7FF3D")
    d.text((96, 90), subtitle, fill="#171717", font=_font(30))
    d.text((80, 640), title, fill="#F5F5F5", font=_font(120))
    d.line([(80, 900), (520, 900)], fill="#FF623B", width=8)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


PAGES = {
    "politica-de-privacidade": ("Política de privacidade", """## Quem somos
[PREENCHER: razão social, CNPJ, endereço e e-mail do encarregado (DPO).]

## Quais dados coletamos
Coletamos apenas os dados necessários para processar seus pedidos e entregas: nome, e-mail, telefone, endereço e, quando exigido para pagamento ou emissão fiscal, CPF. Dados de cartão são tratados exclusivamente pelo Mercado Pago e não ficam armazenados em nossos sistemas.

## Para que usamos
Execução do contrato de compra, entrega, atendimento, prevenção a fraudes e cumprimento de obrigações legais. Comunicações de marketing somente com o seu consentimento, que pode ser revogado a qualquer momento.

## Compartilhamento
Mercado Pago (pagamentos), transportadoras/Melhor Envio (entregas) e provedores de infraestrutura (hospedagem e e-mail).

## Seus direitos (LGPD, art. 18)
Acesso, correção, portabilidade, anonimização/exclusão e revogação de consentimento pela área “Minha conta → Privacidade” ou pelo nosso e-mail de contato.

## Retenção
Dados de pedidos são mantidos pelo prazo exigido pela legislação fiscal e de defesa do consumidor."""),
    "termos-de-uso": ("Termos de uso e de compra", """## Aceite
Ao comprar em nossa loja você concorda com estes termos.

## Preços e pagamento
Preços em reais (R$). Pagamentos processados pelo Mercado Pago. O pedido é confirmado somente após a aprovação do pagamento.

## Estoque
Os itens ficam reservados por tempo limitado após a finalização do pedido. Pedidos não pagos no prazo são cancelados automaticamente.

## Produtos personalizados
Artes enviadas passam por análise. O cliente declara possuir os direitos sobre o conteúdo enviado. Produtos personalizados não podem ser trocados por arrependimento, exceto em caso de defeito.

## Dados da empresa
[PREENCHER: razão social, CNPJ, endereço, telefone e e-mail — Decreto 7.962/2013.]"""),
    "trocas-e-devolucoes": ("Trocas e devoluções", """## Direito de arrependimento
Você pode desistir da compra em até 7 dias corridos após o recebimento (CDC, art. 49). O valor pago, incluindo o frete, é devolvido integralmente.

## Trocas por tamanho
[PREENCHER: regras e prazo para trocas por tamanho, quem paga o frete de retorno.]

## Defeitos
Produtos com defeito podem ser trocados em até 30 dias (CDC, art. 26).

## Como solicitar
Abra uma solicitação em “Minha conta → Suporte” ou fale conosco pelo WhatsApp."""),
    "politica-de-entrega": ("Política de entrega", """## Prazos
O prazo de entrega começa a contar após a confirmação do pagamento e a postagem. Produtos personalizados têm prazo adicional de produção.

## Modalidades
Retirada no local, entrega regional e envio para todo o Brasil via transportadoras parceiras (quando configurado).

## Rastreamento
Você recebe o código de rastreamento por e-mail e pode acompanhar em “Meus pedidos”.

[PREENCHER: endereço de retirada, horários e regras específicas.]"""),
}

FAQS = [
    ("Como funciona a modelagem oversized?", "As peças oversized têm ombro caído, corpo mais largo e comprimento maior. Confira a tabela de medidas na página do produto. Se preferir um caimento mais justo, escolha um tamanho abaixo."),
    ("Quais formas de pagamento vocês aceitam?", "Pix, cartão de crédito e os demais meios habilitados no Mercado Pago. O pagamento é feito no ambiente seguro do Mercado Pago."),
    ("Qual o prazo de entrega?", "O prazo aparece no carrinho e no checkout ao informar o CEP. Ele começa a contar após a confirmação do pagamento."),
    ("Posso personalizar uma camiseta?", "Sim! Acesse “Personalize”, envie sua arte ou frase e escolha a posição da estampa. Nossa equipe revisa antes da produção."),
]


class Command(BaseCommand):
    help = "Popula dados de demonstração (somente desenvolvimento). Use --force para rodar mesmo com DEBUG=False."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--no-images", action="store_true")

    @transaction.atomic
    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts["force"]:
            raise CommandError("Recusado: DEBUG=False. Use --force apenas se tiver certeza (não use em produção com vendas).")
        self.images = not opts["no_images"]

        brand = BrandSettings.load()
        brand = BrandSettings.objects.get(pk=brand.pk)
        if brand.store_name == "NOME DA MARCA" and settings.STORE_NAME:
            brand.store_name = settings.STORE_NAME
        if not brand.manifesto_text:
            brand.manifesto_text = (
                "A gente nasceu no Capão Redondo, Zona Sul de São Paulo. Aqui, arte é ferramenta de transformação "
                "e roupa é linguagem.\n\nCada peça carrega uma mensagem de amor, solidariedade, esperança e cuidado "
                "com a comunidade — feita com qualidade para circular da quebrada pro mundo."
            )
        if settings.STORE_WHATSAPP and not brand.whatsapp_number:
            brand.whatsapp_number = settings.STORE_WHATSAPP
        if settings.STORE_INSTAGRAM and not brand.instagram_url:
            handle = settings.STORE_INSTAGRAM.lstrip("@")
            brand.instagram_url = handle if handle.startswith("http") else f"https://instagram.com/{handle}"
        brand.save()

        sizes = {}
        for i, name in enumerate(["PP", "P", "M", "G", "GG", "XG"]):
            sizes[name], _ = Size.objects.get_or_create(name=name, defaults={"position": i})
        black, _ = Color.objects.get_or_create(name="Preta", defaults={"hex": "#141414", "position": 0})
        white, _ = Color.objects.get_or_create(name="Branca", defaults={"hex": "#F4F2EC", "position": 1})
        olive, _ = Color.objects.get_or_create(name="Verde militar", defaults={"hex": "#4B5320", "position": 2})

        chart, _ = SizeChart.objects.get_or_create(name="Oversized adulto", defaults={
            "rows": "P;58;72;24\nM;61;74;25\nG;64;76;26\nGG;67;78;27\nXG;70;80;28"})
        chart_reg, _ = SizeChart.objects.get_or_create(name="Tradicional adulto", defaults={
            "rows": "P;50;70;20\nM;53;72;21\nG;56;74;22\nGG;59;76;23\nXG;62;78;24"})

        cat_over, _ = Category.objects.get_or_create(slug="camisetas-oversized", defaults={"name": "Camisetas oversized", "position": 0,
                                                     "description": "Modelagem ampla, ombro caído e comprimento estendido."})
        cat_reg, _ = Category.objects.get_or_create(slug="camisetas-tradicionais", defaults={"name": "Camisetas tradicionais", "position": 1})
        cat_custom, _ = Category.objects.get_or_create(slug="personalizaveis", defaults={"name": "Bases para personalizar", "position": 2})

        pcj, _ = Collection.objects.get_or_create(slug="pense-como-jesus", defaults={
            "name": "Pense Como Jesus", "label": "DROP 001", "is_featured": True, "position": 0,
            "tagline": "Amor, solidariedade, esperança e cuidado com a comunidade — estampados com orgulho da Zona Sul.",
            "description": "A primeira coleção apresenta Jesus — retratado com características historicamente plausíveis de um homem judeu do Oriente Médio do século I — cuidando simbolicamente da comunidade do Capão Redondo. Arte principal nas costas, em cores vibrantes; na frente, a frase “Pense como Jesus” em tamanho pequeno, no peito.",
        })
        essentials, _ = Collection.objects.get_or_create(slug="essenciais", defaults={
            "name": "Essenciais", "label": "CORE", "position": 1, "accent": "#FF623B",
            "tagline": "Bases oversized e tradicionais para o dia a dia — e para você personalizar."})
        if self.images and not pcj.cover:
            pcj.cover.save("drop-001.png", ContentFile(poster_image("PENSE COMO JESUS", "DROP 001").getvalue()), save=True)
        if self.images and not essentials.cover:
            essentials.cover.save("essenciais.png", ContentFile(poster_image("ESSENCIAIS", "CORE").getvalue()), save=True)

        common = {
            "fabric": "Malha 100% algodão penteado fio 30.1, 220 g/m²",
            "composition": "100% algodão",
            "care_instructions": "Lave do avesso em água fria.\nNão use alvejante.\nNão passe ferro sobre a estampa.\nSecar à sombra.",
            "status": Product.Status.ACTIVE,
        }
        catalog = [
            dict(sku="PCJ-PRT", name="Camiseta Oversized Pense Como Jesus — Preta", color=black, category=cat_over, chart=chart,
                 price="149.90", cost="48.00", featured=True, badge="LANÇAMENTO", collections=[pcj], fit="oversized",
                 short="Arte principal nas costas, frase “Pense como Jesus” no peito.", art=True,
                 desc=pcj.description, stock=[("P", 8), ("M", 15), ("G", 15), ("GG", 10), ("XG", 4)]),
            dict(sku="PCJ-BRC", name="Camiseta Oversized Pense Como Jesus — Branca", color=white, category=cat_over, chart=chart,
                 price="149.90", cost="46.00", featured=True, badge="LANÇAMENTO", collections=[pcj], fit="oversized",
                 short="Arte principal nas costas, frase “Pense como Jesus” no peito.", art=True,
                 desc=pcj.description, stock=[("P", 6), ("M", 12), ("G", 12), ("GG", 8), ("XG", 3)]),
            dict(sku="BAS-OVR", name="Camiseta Oversized Básica", color=None, category=cat_custom, chart=chart,
                 price="89.90", cost="32.00", featured=False, badge="", collections=[essentials], fit="oversized",
                 short="A base perfeita: oversized, malha encorpada, pronta para personalizar.", art=False, customizable=True,
                 desc="Camiseta oversized lisa em malha encorpada. Disponível como base para personalização.",
                 stock=[("P", 10), ("M", 20), ("G", 20), ("GG", 12), ("XG", 6)], colors=[black, white, olive]),
            dict(sku="BAS-REG", name="Camiseta Tradicional Essencial", color=None, category=cat_reg, chart=chart_reg,
                 price="69.90", cost="25.00", featured=False, badge="", collections=[essentials], fit="regular",
                 short="Modelagem tradicional, corte reto, conforto diário.", art=False, customizable=True,
                 desc="Camiseta de modelagem tradicional em algodão penteado.",
                 stock=[("P", 10), ("M", 15), ("G", 15), ("GG", 8), ("XG", 4)], colors=[black, white]),
        ]
        for data in catalog:
            product, created = Product.objects.get_or_create(sku_base=data["sku"], defaults={
                "name": data["name"], "category": data["category"], "size_chart": data["chart"], "price": Decimal(data["price"]),
                "cost_price": Decimal(data["cost"]), "is_featured": data["featured"], "badge": data["badge"],
                "short_description": data["short"], "description": data["desc"],
                "fit_description": "Oversized: ombro caído e corpo amplo" if data["fit"] == "oversized" else "Tradicional: corte reto",
                "is_customizable": data.get("customizable", False), **common,
            })
            product.collections.set(data["collections"])
            colors = data.get("colors") or [data["color"]]
            for color in colors:
                for size_name, qty in data["stock"]:
                    sku = f"{data['sku']}-{color.slug[:3].upper()}-{size_name}" if data.get("colors") else f"{data['sku']}-{size_name}"
                    variant, v_created = ProductVariant.objects.get_or_create(
                        product=product, color=color, size=sizes[size_name], fit=data["fit"], defaults={"sku": sku})
                    if v_created and qty:
                        record_movement(variant.pk, InventoryMovement.Kind.ENTRY, qty, reason="Estoque de demonstração",
                                        unit_cost=Decimal(data["cost"]))
            if self.images and created and not product.images.exists():
                for pos, color in enumerate(colors):
                    front = shirt_image(color.hex, side="front", label=f"{product.name} · frente",
                                        chest_text="PENSE COMO JESUS" if data["art"] else "")
                    self._add_image(product, front, color if len(colors) > 1 else None, "front", pos * 2)
                    back = shirt_image(color.hex, side="back", label=f"{product.name} · costas", art=data["art"])
                    self._add_image(product, back, color if len(colors) > 1 else None, "back", pos * 2 + 1)
            self.stdout.write(f"  produto: {product.name}")

        ShippingMethod.objects.get_or_create(name="Retirada no Capão Redondo", defaults={
            "kind": ShippingMethod.Kind.PICKUP, "states": "SP", "days_min": 1, "days_max": 3, "position": 0,
            "instructions": "[PREENCHER endereço e horário de retirada] — avisaremos quando estiver pronto."})
        ShippingMethod.objects.get_or_create(name="Entrega expressa — Grande São Paulo", defaults={
            "kind": ShippingMethod.Kind.FIXED, "price": Decimal("19.90"), "free_above": Decimal("299.00"), "states": "SP",
            "cep_ranges": "01000000-09999999", "days_min": 1, "days_max": 4, "position": 1})
        ShippingMethod.objects.get_or_create(name="Melhor Envio (Correios e transportadoras)", defaults={
            "kind": ShippingMethod.Kind.MELHOR_ENVIO, "service_ids": "1,2", "position": 2})

        for i, (code, name, side, fee, box, desc) in enumerate([
            ("peito", "Peito (pequena)", "front", "15.00", (55, 24, 18, 14), "Até 10 cm, lado esquerdo do peito."),
            ("frente", "Frente central", "front", "25.00", (30, 26, 40, 40), "Até 28 cm de largura."),
            ("costas", "Costas inteira", "back", "35.00", (28, 24, 44, 50), "Até 32 cm de largura."),
        ]):
            PrintPlacement.objects.get_or_create(code=code, defaults={
                "name": name, "side": side, "fee": Decimal(fee), "box_left": box[0], "box_top": box[1], "box_width": box[2],
                "box_height": box[3], "description": desc, "position": i})

        for slug, (title, body) in PAGES.items():
            Page.objects.get_or_create(slug=slug, defaults={"title": title, "body": body})
        for i, (q, a) in enumerate(FAQS):
            FAQ.objects.get_or_create(question=q, defaults={"answer": a, "position": i})
        Coupon.objects.get_or_create(code="BEMVINDO10", defaults={
            "kind": Coupon.Kind.PERCENT, "value": Decimal("10"), "first_order_only": True, "max_uses_per_customer": 1,
            "description": "Demonstração: 10% na primeira compra (não cumulativo com promoções)."})

        from apps.dashboard.forms import ensure_groups

        ensure_groups()
        self.stdout.write(self.style.SUCCESS("Dados de demonstração criados. Nenhum pedido ou pagamento foi gerado."))

    def _add_image(self, product, buf, color, view, position):
        main, size, thumb = make_web_versions(buf)
        img = ProductImage(product=product, color=color, view=view, position=position, is_illustrative=True,
                           alt=f"{product.name} — {'frente' if view == 'front' else 'costas'} (imagem ilustrativa)")
        img.image.save(f"{product.sku_base.lower()}-{view}.webp", main, save=False)
        img.thumbnail.save(f"{product.sku_base.lower()}-{view}-thumb.webp", thumb, save=False)
        img.save()
