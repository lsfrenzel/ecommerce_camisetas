from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("webhook/mercadopago/", views.mercadopago_webhook, name="webhook"),
    path("retorno/<uuid:public_id>/", views.payment_return, name="return"),
]
