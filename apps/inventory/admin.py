from django.contrib import admin

from .models import InventoryMovement, InventoryReservation


@admin.register(InventoryMovement)
class MovementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "variant", "kind", "quantity", "stock_after", "user")
    list_filter = ("kind",)
    search_fields = ("variant__sku",)
    readonly_fields = [f.name for f in InventoryMovement._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(InventoryReservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ("order", "variant", "quantity", "status", "expires_at")
    list_filter = ("status",)
    readonly_fields = [f.name for f in InventoryReservation._meta.fields]
