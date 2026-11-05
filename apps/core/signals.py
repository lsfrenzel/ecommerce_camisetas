"""Invalidação de caches de navegação quando o conteúdo muda."""

from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver


def _clear_nav(**kwargs):
    cache.delete_many(["nav-categories", "footer-pages"])


def connect():
    from apps.catalog.models import Category
    from apps.content.models import Page

    for model in (Category, Page):
        post_save.connect(_clear_nav, sender=model, dispatch_uid=f"nav-save-{model.__name__}")
        post_delete.connect(_clear_nav, sender=model, dispatch_uid=f"nav-del-{model.__name__}")


__all__ = ["connect", "receiver"]
