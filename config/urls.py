from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from apps.core.sitemaps import SITEMAPS
from apps.core import views as core_views

admin.site.site_header = "Administração técnica"
admin.site.site_title = "Admin técnico"

urlpatterns = [
    path("healthz/", core_views.healthz, name="healthz"),
    path("robots.txt", core_views.robots_txt, name="robots"),
    path("sitemap.xml", sitemap, {"sitemaps": SITEMAPS}, name="django.contrib.sitemaps.views.sitemap"),
    path("django-admin/", admin.site.urls),
    path("painel/", include("apps.dashboard.urls")),
    path("conta/", include("apps.accounts.urls")),
    path("carrinho/", include("apps.cart.urls")),
    path("pedidos/", include("apps.orders.urls")),
    path("pagamentos/", include("apps.payments.urls")),
    path("frete/", include("apps.shipping.urls")),
    path("personalize/", include("apps.personalization.urls")),
    path("", include("apps.content.urls")),
    path("", include("apps.catalog.urls")),
    path("", include("apps.core.urls")),
]

if not settings.USE_S3:
    if settings.DEBUG:
        urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    elif settings.SERVE_MEDIA_FROM_DISK:
        from django.urls import re_path
        from django.views.static import serve

        urlpatterns += [re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT})]

handler404 = "apps.core.views.error_404"
handler500 = "apps.core.views.error_500"
