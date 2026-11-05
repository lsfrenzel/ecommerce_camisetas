from django.urls import path

from . import views

app_name = "content"

urlpatterns = [
    path("sobre/", views.about, name="about"),
    path("perguntas-frequentes/", views.faq, name="faq"),
    path("p/<slug:slug>/", views.page, name="page"),
    path("newsletter/", views.newsletter_subscribe, name="newsletter"),
    path("newsletter/sair/<str:token>/", views.newsletter_unsubscribe, name="unsubscribe"),
]
