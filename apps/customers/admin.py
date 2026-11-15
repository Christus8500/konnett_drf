from django.contrib import admin
from apps.customers.models import *

# Register your models here.
@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "full_name")
    search_fields = ("user__email", "full_name")
    readonly_fields = ("user", "address", "city", "state", "profile_image")