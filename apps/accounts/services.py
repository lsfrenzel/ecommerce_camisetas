"""Operações de conta relacionadas à LGPD."""

import uuid

from django.db import transaction

from apps.content.models import NewsletterSubscriber


@transaction.atomic
def anonymize_user(user):
    """
    Anonimiza a conta: remove dados pessoais do cadastro, endereços e consentimentos.
    Pedidos são mantidos (obrigação fiscal/consumerista), mas desvinculados da conta.
    """
    original_email = user.email
    NewsletterSubscriber.objects.filter(email__iexact=original_email).delete()
    user.addresses.all().delete()
    profile = user.profile
    profile.phone = ""
    profile.cpf = ""
    profile.birth_date = None
    profile.set_marketing(False)
    profile.staff_notes = ""
    profile.save()
    user.orders.update(user=None)
    user.full_name = "Conta anonimizada"
    user.email = f"anon-{uuid.uuid4().hex[:12]}@anonimo.invalid"
    user.is_active = False
    user.set_unusable_password()
    user.save()
    return user
