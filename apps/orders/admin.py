from django.contrib import admin

from .models import Order, OrderItem, OrderStatusHistory


class ItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = [f.name for f in OrderItem._meta.fields]


class HistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    can_delete = False
    readonly_fields = [f.name for f in OrderStatusHistory._meta.fields]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "customer_name", "email", "status", "payment_status", "total", "created_at")
    list_filter = ("status", "payment_status", "source", "needs_attention")
    search_fields = ("number", "email", "customer_name")
    readonly_fields = ("public_id", "number", "status", "payment_status", "subtotal", "total", "paid_at")
    inlines = [ItemInline, HistoryInline]

    def has_delete_permission(self, request, obj=None):
        return False
