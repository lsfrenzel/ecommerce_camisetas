from django.urls import path

from . import views

app_name = "personalization"

urlpatterns = [
    path("", views.start, name="start"),
    path("minhas/", views.mine, name="mine"),
    path("<uuid:public_id>/", views.detail, name="detail"),
    path("<uuid:public_id>/carrinho/", views.add_to_cart, name="add_to_cart"),
    path("<uuid:public_id>/arte/", views.artwork, name="artwork"),
]
