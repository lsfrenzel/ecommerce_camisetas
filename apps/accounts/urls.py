from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("entrar/", views.login_view, name="login"),
    path("sair/", views.logout_view, name="logout"),
    path("cadastro/", views.signup, name="signup"),
    path("senha/recuperar/", views.PasswordResetView.as_view(), name="password_reset"),
    path("senha/recuperar/enviado/", views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("senha/redefinir/<uidb64>/<token>/", views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("senha/redefinida/", views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("senha/alterar/", views.password_change, name="password_change"),
    path("pedidos/", views.account_orders, name="orders"),
    path("dados/", views.profile, name="profile"),
    path("preferencias/", views.preferences, name="preferences"),
    path("enderecos/", views.addresses, name="addresses"),
    path("enderecos/novo/", views.address_edit, name="address_new"),
    path("enderecos/<int:pk>/", views.address_edit, name="address_edit"),
    path("enderecos/<int:pk>/excluir/", views.address_delete, name="address_delete"),
    path("suporte/", views.support, name="support"),
    path("privacidade/", views.privacy, name="privacy"),
    path("privacidade/exportar/", views.export_data, name="export_data"),
]
