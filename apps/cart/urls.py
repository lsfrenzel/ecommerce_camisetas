from django.urls import path

from . import views

app_name = "cart"

urlpatterns = [
    path("", views.cart_detail, name="detail"),
    path("adicionar/", views.cart_add, name="add"),
    path("item/<int:item_id>/", views.cart_update, name="update"),
    path("item/<int:item_id>/remover/", views.cart_remove, name="remove"),
    path("cupom/", views.apply_coupon, name="coupon"),
    path("cupom/remover/", views.remove_coupon, name="coupon_remove"),
    path("frete/", views.set_shipping, name="shipping"),
    path("checkout/", views.checkout, name="checkout"),
    path("checkout/frete/", views.checkout_shipping, name="checkout_shipping"),
]
