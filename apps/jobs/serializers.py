from django.utils import timezone

from rest_framework import serializers

from apps.providers.models import ProviderProfile
from apps.services.models import Category
from apps.jobs.models import (
    JobRequest,
    JobRequestImage,
    JobCompletionImage,
    JobRequestOffer,
    JobDispute,
)

MAX_IMAGES = 5


class JobRequestImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobRequestImage
        fields = ["id", "image"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        job = self.context["job"]

        if job.job_request_images.count() >= MAX_IMAGES:
            raise serializers.ValidationError("Maximum of 5 images allowed.")
        return attrs


class JobCompletionImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobCompletionImage
        fields = [
            "image",
        ]


class JobRequestOfferSerializer(serializers.ModelSerializer):
    # Nested serializer to include provider details in the job offer representation.
    class MiniProviderProfileSerializer(serializers.ModelSerializer):
        class Meta:
            model = ProviderProfile
            fields = [
                "business_name",
                "years_of_experience",
                "average_rating",
                "completed_jobs",
                "profile_image",
            ]

    provider = MiniProviderProfileSerializer(read_only=True)
    job = serializers.StringRelatedField(read_only=True)
    job_status = serializers.CharField(source="job.status", read_only=True)

    class Meta:
        model = JobRequestOffer
        fields = ["id", "provider", "status", "job", "job_status"]
        read_only_fields = fields


class JobDisputeSerializer(serializers.ModelSerializer):
    customer = serializers.CharField(source="job.customer.fullname", read_only=True)
    job = serializers.CharField(source="job.title", read_only=True)

    class Meta:
        model = JobDispute
        fields = ["id", "job", "customer", "customer_reason", "admin_note", "decision"]
        read_only_fields = ["id", "admin_note", "decision"]


class JobRequestReadSerializer(serializers.ModelSerializer):
    customer = serializers.StringRelatedField()
    category = serializers.StringRelatedField()
    request_images = JobRequestImageSerializer(
        many=True, source="job_request_images", read_only=True
    )
    completion_images = JobCompletionImageSerializer(
        many=True, source="job_completion_images", read_only=True
    )
    offers = JobRequestOfferSerializer(source="job_offers", many=True, read_only=True)
    dispute = JobDisputeSerializer(read_only=True)

    class Meta:
        model = JobRequest
        fields = [
            "id",
            "customer",
            "category",
            "title",
            "description",
            "points_amount",
            "deadline",
            "job_address",
            "city",
            "state",
            "status",
            "created_at",
            "completed_at",
            "request_images",
            "offers",
            "completion_images",
            "dispute",
        ]
        read_only_fields = ["id", "customer", "status", "completed_at", "created_at"]


class JobRequestWriteSerializer(serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())

    class Meta:
        model = JobRequest
        fields = [
            "category",
            "title",
            "description",
            "points_amount",
            "deadline",
            "job_address",
            "city",
            "state",
        ]

    def validate_deadline(self, value):
        if value and value <= timezone.now():
            raise serializers.ValidationError("Deadline must be in the future.")
        return value


class AdminJobDisputeSerializer(serializers.ModelSerializer):
    job = serializers.CharField(source="job.title", read_only=True)
    customer = serializers.CharField(source="job.customer.fullname", read_only=True)

    class Meta:
        model = JobDispute
        fields = ["job", "customer", "customer_reason", "admin_note", "decision"]
        read_only_fields = ["job", "customer", "customer_reason"]
