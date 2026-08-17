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
    # readonly_fields = ("customer", "category", "title", "description", "points_amount", "deadline", "job_address", "job_address_2", "points_amount")

@admin.register(JobRequestImage)
class JobRequestImageAdmin(admin.ModelAdmin):
    list_select_related = ("job__customer__user",)

@admin.register(JobCompletionImage)
class JobCompletionImageAdmin(admin.ModelAdmin):
    list_select_related = ("job", "provider__user", "job__customer__user")


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