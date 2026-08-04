from django.contrib import admin

from apps.konnett_points.models import PointWallet, PointPurchase, PointTransaction

# Register your models here.
admin.site.register(PointWallet)
admin.site.register(PointPurchase)
admin.site.register(PointTransaction)
