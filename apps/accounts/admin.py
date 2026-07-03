from django.contrib import admin
from apps.accounts.models import User

# Register your models here.
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "role")
    list_filter = ("role",)
    search_fields = ("email",)