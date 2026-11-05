from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("loja/", views.shop, name="shop"),
    path("categoria/<slug:category_slug>/", views.shop, name="category"),
    path("colecoes/", views.collections, name="collections"),
    path("colecao/<slug:collection_slug>/", views.shop, name="collection"),
    path("produto/<slug:slug>/", views.product_detail, name="product"),
]
