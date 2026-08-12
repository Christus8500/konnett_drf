from django.contrib import admin

from apps.konnett_points.models import PointWallet, PointPurchase, PointTransaction

# Register your models here.
admin.site.register(PointWallet)


@admin.register(PointTransaction)
class PointTransactionAdmin(admin.ModelAdmin):
    search_fields = ("transaction_reference",)


@admin.register(PointPurchase)
class PointPurchaseAdmin(admin.ModelAdmin):
    list_filter = ("status",)
    search_fields = ("payment_reference",)
    readonly_fields = ("payment_reference", )
