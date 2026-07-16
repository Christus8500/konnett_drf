from django.contrib import admin
from apps.providers.models import ProviderProfile, ProviderVerification

# Register your models here.
@admin.register(ProviderProfile)
class ProviderProfileAdmin(admin.ModelAdmin):
    list_display = ("fullname", "is_verified", "is_available")
    search_fields = ("user__email",)


@admin.register(ProviderVerification)
class ProviderVerificationAdmin(admin.ModelAdmin):
    list_display = ("provider", "status")
    list_filter = ("status",)