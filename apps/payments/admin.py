from django.contrib import admin

from .models import Payment, PaymentEvent


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("order", "provider", "external_id", "status", "amount", "created_at")
    list_filter = ("provider", "status")
    search_fields = ("external_id", "preference_id", "order__number")
    readonly_fields = [f.name for f in Payment._meta.fields]


@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "topic", "resource_id", "signature_valid", "processed", "attempts", "error")
    list_filter = ("topic", "processed", "signature_valid")
    readonly_fields = [f.name for f in PaymentEvent._meta.fields]
