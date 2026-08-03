from django.contrib import admin

from apps.jobs.models import JobRequest, JobRequestImage, JobCompletionImage, JobRequestOffer, JobDispute

# Register your models here.
class JobRequestImageInline(admin.TabularInline):
    model = JobRequestImage

@admin.register(JobRequest)
class JobRequestAdmin(admin.ModelAdmin):
    inlines = [JobRequestImageInline]

    list_display = ("title", "customer", "category", "points_amount", "deadline", "status")
    search_fields = ("title", "category__name", "customer__user__email")
    list_filter = ("status", "category__name")

admin.site.register(JobRequestImage)
admin.site.register(JobCompletionImage)

@admin.register(JobRequestOffer)
class JobRequestOfferAdmin(admin.ModelAdmin):
    list_display = ["job", "provider", "status"]
    search_fields = ["provider",]
    list_filter = ["status",]

@admin.register(JobDispute)
class JobDisputeAdmin(admin.ModelAdmin):
    list_display = ["job", "decision", "resolved_by"]
    list_filter = ["decision",]
    search_fields = ["resolved_by",]