from django.urls import path

from . import brand, views
from .crud import build_cruds

app_name = "dashboard"

CRUDS = build_cruds()

urlpatterns = [
    path("", views.home, name="home"),
    path("produtos/", views.product_list, name="products"),
    path("produtos/novo/", views.product_edit, name="product_new"),
    path("produtos/precos-em-lote/", views.bulk_price, name="bulk_price"),
    path("produtos/<int:pk>/", views.product_edit, name="product_edit"),
    path("produtos/<int:pk>/variacoes/", views.product_generate_variants, name="product_generate_variants"),
    path("produtos/<int:pk>/duplicar/", views.product_duplicate, name="product_duplicate"),
    path("produtos/<int:pk>/arquivar/", views.product_archive, name="product_archive"),
    path("estoque/", views.inventory_view, name="inventory"),
    path("estoque/historico/", views.inventory_history, name="inventory_history"),
    path("pedidos/", views.order_list, name="orders"),
    path("pedidos/<str:number>/", views.order_detail, name="order_detail"),
    path("pedidos/<str:number>/status/", views.order_status, name="order_status"),
    path("pedidos/<str:number>/cancelar/", views.order_cancel, name="order_cancel"),
    path("pedidos/<str:number>/envio/", views.order_shipment, name="order_shipment"),
    path("pedidos/<str:number>/pagamento-manual/", views.order_manual_payment, name="order_manual_payment"),
    path("pedidos/<str:number>/reconciliar/", views.order_reconcile, name="order_reconcile"),
    path("pedidos/<str:number>/resolver/", views.order_resolve_attention, name="order_resolve"),
    path("clientes/", views.customer_list, name="customers"),
    path("clientes/<int:pk>/", views.customer_detail, name="customer_detail"),
    path("personalizacoes/", views.personalization_list, name="personalizations"),
    path("personalizacoes/<uuid:public_id>/", views.personalization_detail, name="personalization_detail"),
    path("relatorios/", views.reports, name="reports"),
    path("equipe/", views.team, name="team"),
    path("equipe/<int:pk>/papel/", views.team_role, name="team_role"),
    path("atendimento/", views.support_list, name="support"),
    path("lgpd/", views.data_requests, name="data_requests"),
    path("auditoria/", views.audit_log, name="audit"),
    path("newsletter.csv", views.newsletter_export, name="newsletter_export"),
    path("marca/", brand.brand_settings, name="brand"),
]

for crud in CRUDS:
    urlpatterns += crud.urls()
