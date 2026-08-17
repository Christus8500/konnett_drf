from django.contrib import admin
from apps.services.models import Category, Service


# Register your models here.
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "slug")
    search_fields = ("name",)


@admin.register(Service)
class ProviderServiceAdmin(admin.ModelAdmin):
    list_display = ("title", "provider", "category", "minimum_points", "is_active")
    search_fields = ("title",)
    list_filter = ("category__name", "is_active")
    readonly_fields = ("provider", "category", "title", "description", "minimum_points", "is_active")

    # ^^ When the app grows and there are many services,
    # ^^ it is better to use select_related to reduce the number of queries made to the database.
    # search_fields = (
    #     "title",
    #     "provider__user__first_name",
    #     "provider__user__last_name",
    #     "provider__user__email",
    #     "category__name",
    # )
    # list_filter = (
    #     "category",
    #     "is_active",
    # )
    # list_select_related = (
    #     "provider",
    #     "category",
    # )
    # ordering = ("title",)
