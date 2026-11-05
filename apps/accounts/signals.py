from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import CustomerProfile, User


@receiver(post_save, sender=User)
def ensure_profile(sender, instance, created, **kwargs):
    if created:
        CustomerProfile.objects.get_or_create(user=instance)


@receiver(user_logged_in)
def merge_cart_on_login(sender, request, user, **kwargs):
    if request is None:
        return
    from apps.cart.services import merge_session_cart_into_user

    merge_session_cart_into_user(request, user)
