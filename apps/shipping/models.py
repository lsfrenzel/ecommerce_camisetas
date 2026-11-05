from django.db import models

from apps.core.models import TimeStampedModel
from apps.core.utils import only_digits


class ShippingMethod(TimeStampedModel):
    class Kind(models.TextChoices):
        PICKUP = "pickup", "Retirada no local"
        FIXED = "fixed", "Frete fixo regional"
        MELHOR_ENVIO = "melhor_envio", "Melhor Envio (cotação em tempo real)"

    name = models.CharField("nome exibido", max_length=80)
    kind = models.CharField("tipo", max_length=20, choices=Kind.choices)
    is_active = models.BooleanField("ativo", default=True)
    price = models.DecimalField("valor (frete fixo)", max_digits=8, decimal_places=2, default=0)
    free_above = models.DecimalField("grátis acima de (R$)", max_digits=10, decimal_places=2, null=True, blank=True)
    states = models.CharField("UFs atendidas", max_length=120, blank=True,
                              help_text="Separe por vírgula (ex.: SP,RJ). Vazio = todo o Brasil.")
    cep_ranges = models.TextField("faixas de CEP", blank=True,
                                  help_text="Opcional. Uma faixa por linha: 04000000-04999999")
    days_min = models.PositiveSmallIntegerField("prazo mínimo (dias úteis)", default=1)
    days_max = models.PositiveSmallIntegerField("prazo máximo (dias úteis)", default=5)
    instructions = models.TextField("instruções (ex.: endereço de retirada)", blank=True)
    service_ids = models.CharField("IDs de serviço Melhor Envio", max_length=60, blank=True,
                                   help_text="Ex.: 1,2 (PAC, SEDEX). Vazio = todos os serviços da conta.")
    extra_days = models.PositiveSmallIntegerField("dias de manuseio adicionais", default=1)
    position = models.PositiveIntegerField("ordem", default=0)

    class Meta:
        ordering = ["position", "name"]
        verbose_name = "método de entrega"
        verbose_name_plural = "métodos de entrega"

    def __str__(self):
        return self.name

    @property
    def state_list(self):
        return [s.strip().upper() for s in self.states.split(",") if s.strip()]

    def cep_range_list(self):
        ranges = []
        for line in self.cep_ranges.splitlines():
            if "-" not in line:
                continue
            start, end = line.split("-", 1)
            start, end = only_digits(start), only_digits(end)
            if len(start) == 8 and len(end) == 8:
                ranges.append((int(start), int(end)))
        return ranges


class Shipment(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Aguardando postagem"
        READY_FOR_PICKUP = "ready_for_pickup", "Pronto para retirada"
        POSTED = "posted", "Postado"
        IN_TRANSIT = "in_transit", "Em trânsito"
        OUT_FOR_DELIVERY = "out_for_delivery", "Saiu para entrega"
        DELIVERED = "delivered", "Entregue"
        RETURNED = "returned", "Devolvido"

    order = models.OneToOneField("orders.Order", on_delete=models.CASCADE, related_name="shipment")
    carrier = models.CharField("transportadora", max_length=80, blank=True)
    service = models.CharField("serviço", max_length=80, blank=True)
    tracking_code = models.CharField("código de rastreamento", max_length=60, blank=True, db_index=True)
    tracking_url = models.URLField("link de rastreamento", blank=True)
    status = models.CharField("status", max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    posted_at = models.DateTimeField("postado em", null=True, blank=True)
    delivered_at = models.DateTimeField("entregue em", null=True, blank=True)
    notes = models.TextField("observações", blank=True)

    class Meta:
        verbose_name = "envio"
        verbose_name_plural = "envios"

    def __str__(self):
        return f"Envio do pedido {self.order.number}"

    @property
    def public_tracking_url(self):
        if self.tracking_url:
            return self.tracking_url
        if self.tracking_code:
            return f"https://rastreamento.correios.com.br/app/index.php?objetos={self.tracking_code}"
        return ""
