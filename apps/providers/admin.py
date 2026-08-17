from django.contrib import admin
from apps.providers.models import ProviderProfile, ProviderVerification


# Register your models here.
@admin.register(ProviderProfile)
class ProviderProfileAdmin(admin.ModelAdmin):
    list_display = ("fullname", "is_verified", "is_available")
    search_fields = ("user__email", "fullname")
    list_filter = ("is_verified",)
    readonly_fields = ("user", "business_name", "bio", "years_of_experience", "average_rating", "completed_jobs", "profile_image", "account_number", "account_name", "bank_name")


@admin.register(ProviderVerification)
class ProviderVerificationAdmin(admin.ModelAdmin):
    list_display = ("provider", "status")
    list_filter = ("status",)
    readonly_fields = ("provider", "id_document", "selfie_image", "submitted_at")
