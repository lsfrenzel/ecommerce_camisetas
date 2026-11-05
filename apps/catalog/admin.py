from django.contrib import admin

from .models import Category, Collection, Color, Product, ProductImage, ProductVariant, Size, SizeChart


class VariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    readonly_fields = ("stock", "reserved")


class ImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku_base", "category", "price", "status", "is_featured", "sold_count")
    list_filter = ("status", "category", "collections", "is_featured")
    search_fields = ("name", "sku_base", "variants__sku")
    inlines = [VariantInline, ImageInline]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ProductVariant)
class VariantAdmin(admin.ModelAdmin):
    list_display = ("sku", "product", "color", "size", "fit", "stock", "reserved", "is_active")
    search_fields = ("sku", "product__name")
    list_filter = ("fit", "color", "size")
    readonly_fields = ("stock", "reserved")


admin.site.register([Category, Collection, Color, Size, SizeChart])
