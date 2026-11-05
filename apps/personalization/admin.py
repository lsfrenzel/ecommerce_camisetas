from django.contrib import admin

from .models import PersonalizationRequest, PrintPlacement

admin.site.register([PersonalizationRequest, PrintPlacement])
