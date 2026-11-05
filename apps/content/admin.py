from django.contrib import admin

from .models import FAQ, Banner, BrandSettings, NewsletterSubscriber, Page

admin.site.register([BrandSettings, Banner, Page, FAQ])


@admin.register(NewsletterSubscriber)
class NewsletterAdmin(admin.ModelAdmin):
    list_display = ("email", "consent_at", "unsubscribed_at", "source")
    search_fields = ("email",)
