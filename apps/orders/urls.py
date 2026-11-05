from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("", views.order_list, name="list"),
    path("<uuid:public_id>/", views.order_detail, name="detail"),
    path("<uuid:public_id>/pagar/", views.order_pay, name="pay"),
]
