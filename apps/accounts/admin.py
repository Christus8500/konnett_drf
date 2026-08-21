from django.contrib import admin
from apps.accounts.models import User


# Register your models here.
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "role", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("email", "phone_number")
    readonly_fields = ("email", "phone_number", "first_name", "last_name")
