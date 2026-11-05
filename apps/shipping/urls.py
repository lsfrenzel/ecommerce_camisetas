from django.urls import path

from . import views

app_name = "shipping"

urlpatterns = [
    path("cotar/", views.quote_view, name="quote"),
]
