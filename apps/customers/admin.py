from django.contrib import admin
from apps.customers.models import *

# Register your models here.
@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "fullname")
    search_fields = ("user__email", "fullname")
    readonly_fields = ("user", "address", "city", "state", "profile_image")