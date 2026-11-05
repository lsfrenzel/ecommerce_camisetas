"""Utilidades compartilhadas: dinheiro, documentos brasileiros, CEP."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError

CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def format_brl(value) -> str:
    value = money(value)
    sign = "-" if value < 0 else ""
    integer, cents = f"{abs(value):.2f}".split(".")
    groups = []
    while integer:
        groups.insert(0, integer[-3:])
        integer = integer[:-3]
    return f"{sign}R$ {'.'.join(groups)},{cents}"


def only_digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def is_valid_cpf(value: str) -> bool:
    cpf = only_digits(value)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for i in (9, 10):
        total = sum(int(cpf[n]) * ((i + 1) - n) for n in range(i))
        digit = (total * 10) % 11 % 10
        if digit != int(cpf[i]):
            return False
    return True


def validate_cpf(value: str) -> None:
    if not is_valid_cpf(value):
        raise ValidationError("CPF inválido.")


def format_cpf(value: str) -> str:
    d = only_digits(value)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else value


def validate_cep(value: str) -> None:
    if len(only_digits(value)) != 8:
        raise ValidationError("CEP deve ter 8 dígitos.")


def format_cep(value: str) -> str:
    d = only_digits(value)
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else value


def validate_phone(value: str) -> None:
    if len(only_digits(value)) not in (10, 11):
        raise ValidationError("Informe um telefone com DDD.")


UF_CHOICES = [
    ("AC", "Acre"), ("AL", "Alagoas"), ("AP", "Amapá"), ("AM", "Amazonas"), ("BA", "Bahia"),
    ("CE", "Ceará"), ("DF", "Distrito Federal"), ("ES", "Espírito Santo"), ("GO", "Goiás"),
    ("MA", "Maranhão"), ("MT", "Mato Grosso"), ("MS", "Mato Grosso do Sul"), ("MG", "Minas Gerais"),
    ("PA", "Pará"), ("PB", "Paraíba"), ("PR", "Paraná"), ("PE", "Pernambuco"), ("PI", "Piauí"),
    ("RJ", "Rio de Janeiro"), ("RN", "Rio Grande do Norte"), ("RS", "Rio Grande do Sul"),
    ("RO", "Rondônia"), ("RR", "Roraima"), ("SC", "Santa Catarina"), ("SP", "São Paulo"),
    ("SE", "Sergipe"), ("TO", "Tocantins"),
]

# Faixas de CEP por UF (Correios). Usadas para regras de frete regional.
_CEP_RANGES = [
    ("SP", 1000000, 19999999), ("RJ", 20000000, 28999999), ("ES", 29000000, 29999999),
    ("MG", 30000000, 39999999), ("BA", 40000000, 48999999), ("SE", 49000000, 49999999),
    ("PE", 50000000, 56999999), ("AL", 57000000, 57999999), ("PB", 58000000, 58999999),
    ("RN", 59000000, 59999999), ("CE", 60000000, 63999999), ("PI", 64000000, 64999999),
    ("MA", 65000000, 65999999), ("PA", 66000000, 68899999), ("AP", 68900000, 68999999),
    ("AM", 69000000, 69299999), ("RR", 69300000, 69399999), ("AM", 69400000, 69899999),
    ("AC", 69900000, 69999999), ("DF", 70000000, 72799999), ("GO", 72800000, 72999999),
    ("DF", 73000000, 73699999), ("GO", 73700000, 76799999), ("TO", 77000000, 77999999),
    ("MT", 78000000, 78899999), ("RO", 76800000, 76999999), ("MS", 79000000, 79999999),
    ("PR", 80000000, 87999999), ("SC", 88000000, 89999999), ("RS", 90000000, 99999999),
]


def uf_from_cep(cep: str) -> str | None:
    digits = only_digits(cep)
    if len(digits) != 8:
        return None
    number = int(digits)
    for uf, start, end in _CEP_RANGES:
        if start <= number <= end:
            return uf
    return None
