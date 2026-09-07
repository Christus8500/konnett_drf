from django.db import transaction
from django.utils import timezone

from rest_framework import serializers

from apps.core.constants import MAX_JOB_REQUEST_IMAGES
from apps.core.validators import validate_image
from apps.core.models import Address
from apps.core.serializers import AddressSerializer

from apps.providers.models import ProviderProfile

from apps.services.models import Category

from apps.jobs.models import (
    JobRequest,
    JobRequestImage,
    JobCompletionImage,
    JobRequestOffer,
    JobDispute,
)


class JobRequestImageSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(
        validators=[validate_image],
    )

    class Meta:
        model = JobRequestImage
        fields = ["id", "image"]
        read_only_fields = ["id"]


class JobConfirmCompletionSerializer(serializers.Serializer):
    rating = serializers.IntegerField(
        min_value=1,
        max_value=5
    )


class JobCompletionImageSerializer(serializers.Serializer):
    images = serializers.ListField(
        child=serializers.ImageField(validators=[validate_image]),
        allow_empty=False,
    )


class JobRequestOfferSerializer(serializers.ModelSerializer):
    class MiniProviderProfileSerializer(serializers.ModelSerializer):
        class Meta:
            model = ProviderProfile
            fields = [
                "business_name",
                "years_of_experience",
                "average_rating",
                "ratings_count",
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
    customer = serializers.CharField(
        source="job.customer.fullname",
        read_only=True,
    )
    job = serializers.CharField(
        source="job.title",
        read_only=True,
    )

    class Meta:
        model = JobDispute
        fields = [
            "id",
            "job",
            "customer",
            "customer_reason",
            "admin_note",
            "decision",
        ]
        read_only_fields = [
            "id",
            "admin_note",
            "decision",
        ]


class JobRequestReadSerializer(serializers.ModelSerializer):
    customer = serializers.StringRelatedField()
    category = serializers.StringRelatedField()

    primary_location = AddressSerializer(read_only=True)
    secondary_location = AddressSerializer(read_only=True)

    request_images = JobRequestImageSerializer(
        many=True,
        source="job_request_images",
        read_only=True,
    )

    completion_images = JobCompletionImageSerializer(
        many=True,
        source="job_completion_images",
        read_only=True,
    )

    offers = JobRequestOfferSerializer(
        source="job_offers",
        many=True,
        read_only=True,
    )

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
            "primary_location",
            "secondary_location",
            "status",
            "created_at",
            "completed_at",
            "request_images",
            "offers",
            "completion_images",
            "dispute",
        ]

        read_only_fields = [
            "id",
            "customer",
            "status",
            "completed_at",
            "created_at",
        ]


class JobRequestWriteSerializer(serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())

    primary_location = AddressSerializer()

    secondary_location = AddressSerializer(
        required=False,
        allow_null=True,
    )

    images = serializers.ListField(
        child=serializers.ImageField(),
        write_only=True,
        required=True,
        allow_empty=False,
    )

    class Meta:
        model = JobRequest
        fields = [
            "category",
            "title",
            "description",
            "points_amount",
            "deadline",
            "primary_location",
            "secondary_location",
            "images",
        ]

    def validate_deadline(self, value):
        if value and value <= timezone.now():
            raise serializers.ValidationError("Deadline must be in the future.")

        return value

    def validate(self, attrs):
        category = attrs.get("category")
        secondary_location = attrs.get("secondary_location")

        if category and category.requires_secondary_location and not secondary_location:
            raise serializers.ValidationError(
                {
                    "secondary_location": (
                        "A secondary location is required for this category."
                    )
                }
            )

        images = attrs.get("images", [])

        if len(images) > MAX_JOB_REQUEST_IMAGES:
            raise serializers.ValidationError(
                {
                    "images": (
                        f"A maximum of {MAX_JOB_REQUEST_IMAGES} "
                        "images can be uploaded."
                    )
                }
            )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        # Images are handled by the view.
        validated_data.pop("images", None)

        primary_location_data = validated_data.pop("primary_location")

        secondary_location_data = validated_data.pop(
            "secondary_location",
            None,
        )

        primary_location = Address.objects.create(**primary_location_data)

        secondary_location = None

        if secondary_location_data:
            secondary_location = Address.objects.create(**secondary_location_data)

        return JobRequest.objects.create(
            primary_location=primary_location,
            secondary_location=secondary_location,
            **validated_data,
        )


class AdminJobDisputeSerializer(serializers.ModelSerializer):
    job = serializers.CharField(
        source="job.title",
        read_only=True,
    )
    customer = serializers.CharField(
        source="job.customer.fullname",
        read_only=True,
    )

    class Meta:
        model = JobDispute
        fields = [
            "job",
            "customer",
            "customer_reason",
            "admin_note",
            "decision",
        ]
        read_only_fields = [
            "job",
            "customer",
            "customer_reason",
        ]
