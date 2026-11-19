import hashlib

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from rest_framework import serializers

from drf_spectacular.utils import extend_schema_field

from apps.core.constants import MAX_JOB_REQUEST_IMAGES, MINIMUM_JOB_POINTS
from apps.core.validators import validate_image
from apps.core.models import Address
from apps.core.serializers import AddressSerializer
from apps.core.choices import JobOfferStatus, JobDisputeDecision

from apps.providers.models import ProviderProfile

from apps.services.models import Category

from apps.jobs.models import (
    JobRequest,
    JobRequestImage,
    JobCompletionImage,
    JobRequestOffer,
    JobDispute,
    ProviderRating,
    JobProgressUpdate,
)


class JobRequestImageSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(
        validators=[validate_image],
    )

    class Meta:
        model = JobRequestImage
        fields = ["id", "image"]
        read_only_fields = ["id"]


class JobRatingSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(
        required=False, allow_blank=True, max_length=1000
    )


class JobConfirmCompletionSerializer(serializers.Serializer):
    # Rating is optional here. The customer can also rate later via
    # POST /jobs/<id>/rating/.
    rating = serializers.IntegerField(
        min_value=1, max_value=5, required=False, allow_null=True
    )
    comment = serializers.CharField(
        required=False, allow_blank=True, max_length=1000
    )

    def validate(self, attrs):
        if attrs.get("comment") and attrs.get("rating") is None:
            raise serializers.ValidationError(
                {"rating": "A rating is required when leaving a comment."}
            )
        return attrs


class ProviderRatingSerializer(serializers.ModelSerializer):
    reviewer = serializers.SerializerMethodField()
    # Month and year only, so a provider can't match a comment to a specific job by timing
    created_at = serializers.DateTimeField(format="%B %Y", read_only=True)

    class Meta:
        model = ProviderRating
        fields = ["id", "rating", "comment", "reviewer", "created_at"]
        read_only_fields = fields

    def get_reviewer(self, obj):
        raw = f"{settings.REVIEWER_LABEL_SALT}:{obj.customer_id}:{obj.provider_id}"
        return f"user{hashlib.sha256(raw.encode()).hexdigest()[:4]}..."


class JobCompletionImageSerializer(serializers.Serializer):
    images = serializers.ListField(
        child=serializers.ImageField(validators=[validate_image]),
        allow_empty=False,
    )


class JobCompletionImageReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobCompletionImage
        fields = ["id", "image", "created_at"]
        read_only_fields = fields


class JobProgressUpdateSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(required=False, validators=[validate_image])

    class Meta:
        model = JobProgressUpdate
        fields = ["id", "note", "image", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        if not attrs.get("note") and not attrs.get("image"):
            raise serializers.ValidationError(
                "A progress update needs a note or an image."
            )
        return attrs


class JobRequestOfferSerializer(serializers.ModelSerializer):
    class MiniProviderProfileSerializer(serializers.ModelSerializer):
        class Meta:
            model = ProviderProfile
            fields = [
                "id",
                "business_name",
                "years_of_experience",
                "average_rating",
                "ratings_count",
                "completed_jobs",
                "profile_image",
            ]

    provider = MiniProviderProfileSerializer(read_only=True)
    job = serializers.CharField(source="job.title", read_only=True)
    job_id = serializers.UUIDField(read_only=True)
    job_status = serializers.CharField(source="job.status", read_only=True)

    class Meta:
        model = JobRequestOffer
        fields = ["id", "provider", "status", "job", "job_id", "job_status"]
        read_only_fields = fields


class JobDisputeSerializer(serializers.ModelSerializer):
    customer = serializers.CharField(source="job.customer.full_name", read_only=True)
    job = serializers.CharField(source="job.title", read_only=True)

    class Meta:
        model = JobDispute
        fields = [
            "id",
            "job",
            "customer",
            "source",
            "customer_reason",
            "system_reason",
            "provider_response",
            "admin_note",
            "decision",
        ]
        read_only_fields = [
            "id",
            "source",
            "system_reason",
            "provider_response",
            "admin_note",
            "decision",
        ]
        # The model field is blank=True (system disputes have no customer
        # reason), but a customer must always give one.
        extra_kwargs = {
            "customer_reason": {"required": True, "allow_blank": False},
        }


class ProviderDisputeResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobDispute
        fields = ["id", "provider_response", "provider_responded_at"]
        read_only_fields = ["id", "provider_responded_at"]
        extra_kwargs = {
            "provider_response": {
                "required": True,
                "allow_blank": False,
                "max_length": 2000,
            },
        }


class JobRequestReadSerializer(serializers.ModelSerializer):
    customer = serializers.SerializerMethodField()
    category = serializers.StringRelatedField()

    primary_location = serializers.SerializerMethodField()
    secondary_location = serializers.SerializerMethodField()

    request_images = JobRequestImageSerializer(
        many=True,
        source="job_request_images",
        read_only=True,
    )

    completion_images = JobCompletionImageReadSerializer(
        many=True,
        source="job_completion_images",
        read_only=True,
    )

    offers = JobRequestOfferSerializer(
        source="job_offers",
        many=True,
        read_only=True,
    )

    offers = serializers.SerializerMethodField()

    progress_updates = serializers.SerializerMethodField()

    auto_release_at = serializers.DateTimeField(
        read_only=True,
        help_text=(
            "UI: for AWAITING_CONFIRMATION jobs, show the customer a countdown to "
            "this time. After it, payment is released automatically and disputes "
            "are no longer accepted. Null if the job has no deadline."
        ),
    )
    can_rate = serializers.SerializerMethodField()

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
            "created_at",
            "status",
            "started_at",
            "completion_requested_at",
            "auto_release_at",
            "can_rate",
            "completed_at",
            "request_images",
            "offers",
            "progress_updates",
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

    def get_customer(self, job):
        if self._can_see_full_details(job):
            return job.customer.full_name
        return job.customer.user.first_name or "Customer"

    def get_offers(self, job):
        user = self.context["request"].user

        # job_offers is prefetched, so this uses the cache. Don't add .filter() here.
        offers = list(job.job_offers.all())

        is_owner = job.customer.user_id == user.id
        if not (user.is_staff or is_owner):
            # Providers only ever see their own offer.
            offers = [o for o in offers if o.provider.user_id == user.id]

        return JobRequestOfferSerializer(offers, many=True, context=self.context).data

    def get_progress_updates(self, job):
        # Same audience as the full address: owner, accepted provider, admin.
        if not self._can_see_full_details(job):
            return []
        # job_progress_updates is prefetched (Step 7c), so this uses the cache.
        return JobProgressUpdateSerializer(
            job.job_progress_updates.all(), many=True, context=self.context
        ).data

    # UI NOTE: show the "Rate provider" form only when can_rate is true, and
    # submit it to POST /jobs/<id>/rating/. Don't work this out from job.status
    # on the client. It covers COMPLETED jobs and jobs closed by an admin dispute
    # decision (refund, partial pay, release), and it turns false once rated.
    # Rating at confirmation is optional, so can_rate stays true after a
    # completed job if the customer skipped it.
    @extend_schema_field(
        {
            "type": "boolean",
            "description": (
                "UI: show the 'Rate provider' form only when true; submit to "
                "POST /jobs/{id}/rating/. True only for the job owner, once the job "
                "is completed or its dispute was resolved by an admin (any outcome), "
                "and not yet rated. Do not derive this from `status` on the client. "
                "Rating at confirmation is optional, so this stays true after "
                "completion if the customer skipped it."
            ),
        }
    )
    def get_can_rate(self, job):
        user = self.context["request"].user
        return (
            job.customer.user_id == user.id
            and job.is_ratable()
            and not hasattr(job, "provider_rating")
        )

    def _can_see_full_details(self, job):
        """
        Full address: admin, the job's customer, or the accepted provider.
        Uses the prefetched job_offers, so it adds no queries.
        """
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return False

        user = request.user

        if user.is_staff or job.customer.user_id == user.id:
            return True

        return any(
            offer.status == JobOfferStatus.ACCEPTED
            and offer.provider.user_id == user.id
            for offer in job.job_offers.all()
        )

    def _serialize_location(self, job, address):
        if address is None:
            return None

        if self._can_see_full_details(job):
            return AddressSerializer(address, context=self.context).data

        # Everyone else: area only. No street, no coordinates, no address id.
        return {"city": address.city, "state": address.state}

    def get_primary_location(self, job):
        return self._serialize_location(job, job.primary_location)

    def get_secondary_location(self, job):
        return self._serialize_location(job, job.secondary_location)


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

    def validate_points_amount(self, value):
        if value < MINIMUM_JOB_POINTS:
            raise serializers.ValidationError(
                f"Points amount must be at least {MINIMUM_JOB_POINTS}."
            )
        return value

    def validate(self, attrs):
        instance = self.instance  # None on create

        category = attrs.get("category") or (instance.category if instance else None)

        # On a PATCH, fall back to what the job already has.
        if "secondary_location" in attrs:
            secondary_location = attrs["secondary_location"]
        else:
            secondary_location = instance.secondary_location if instance else None

        if category and category.requires_secondary_location and not secondary_location:
            raise serializers.ValidationError(
                {
                    "secondary_location": (
                        "A secondary location is required for this category."
                    )
                }
            )

        images = attrs.get("images", [])
        existing_images = instance.job_request_images.count() if instance else 0

        if existing_images + len(images) > MAX_JOB_REQUEST_IMAGES:
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
    def update(self, instance, validated_data):
        # Images are handled by the view (perform_update).
        validated_data.pop("images", None)

        primary_data = validated_data.pop("primary_location", None)
        secondary_data = validated_data.pop("secondary_location", None)

        if primary_data:
            for field, value in primary_data.items():
                setattr(instance.primary_location, field, value)
            instance.primary_location.save()

        if secondary_data:
            if instance.secondary_location is None:
                instance.secondary_location = Address.objects.create(**secondary_data)
            else:
                for field, value in secondary_data.items():
                    setattr(instance.secondary_location, field, value)
                instance.secondary_location.save()

        return super().update(instance, validated_data)

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
    job = serializers.CharField(source="job.title", read_only=True)
    customer = serializers.CharField(source="job.customer.full_name", read_only=True)
    job_started_at = serializers.DateTimeField(source="job.started_at", read_only=True)
    job_deadline = serializers.DateTimeField(source="job.deadline", read_only=True)
    accepted_at = serializers.SerializerMethodField()
    progress_updates = serializers.SerializerMethodField()
    completion_images = serializers.SerializerMethodField()

    class Meta:
        model = JobDispute
        fields = [
            "id", "job", "customer", "source",
            "customer_reason", "system_reason",
            "provider_response", "provider_responded_at",
            "job_started_at", "job_deadline", "accepted_at",
            "progress_updates", "completion_images",
            "admin_note", "decision", "provider_percentage",
            "resolved_at",
        ]
        read_only_fields = [
            "id", "customer_reason", "system_reason", "source",
            "provider_response", "provider_responded_at", "resolved_at",
        ]

    def get_accepted_at(self, dispute):
        offer = dispute.job.job_offers.filter(status=JobOfferStatus.ACCEPTED).first()
        return offer.updated_at if offer else None

    def get_progress_updates(self, dispute):
        return JobProgressUpdateSerializer(
            dispute.job.job_progress_updates.all(),
            many=True, context=self.context,
        ).data

    def get_completion_images(self, dispute):
        return JobCompletionImageReadSerializer(
            dispute.job.job_completion_images.all(),
            many=True, context=self.context,
        ).data

    def validate(self, attrs):
        decision = attrs.get("decision")
        pct = attrs.get("provider_percentage")
        if decision == JobDisputeDecision.PARTIAL_PAY:
            if not pct:
                raise serializers.ValidationError(
                    {"provider_percentage": "Required for partial pay (1-99)."}
                )
        elif pct is not None:
            raise serializers.ValidationError(
                {"provider_percentage": "Only allowed with partial_pay."}
            )
        return attrs


# ---------- Documentation-only serializers and reusable pieces ----------
class JobsDetailResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


class JobCompletionConfirmedResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
    rating = serializers.IntegerField(allow_null=True)
    comment = serializers.CharField(allow_blank=True)
    provider_average_rating = serializers.FloatField()
    provider_ratings_count = serializers.IntegerField()


class JobStartedResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
    started_at = serializers.DateTimeField()
