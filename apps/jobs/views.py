from functools import partial

from django.db import transaction
from django.db.models import F, Prefetch, Avg
from django.shortcuts import get_object_or_404

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import viewsets, generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.exceptions import ValidationError
from rest_framework.throttling import (
    ScopedRateThrottle,
    UserRateThrottle,
    AnonRateThrottle,
)

from drf_spectacular.utils import extend_schema, OpenApiResponse

from apps.core.permissions import IsCustomer, IsCustomerOwner, IsVerifiedProvider
from apps.core.choices import (
    JobRequestStatus,
    JobOfferStatus,
    JobDisputeDecision,
    TransactionType,
    UserRole,
)
from apps.core.constants import MAX_JOB_COMPLETION_IMAGES, MAX_JOB_REQUEST_IMAGES

from apps.accounts.models import User

from apps.jobs.models import (
    JobRequest,
    JobRequestImage,
    JobRequestOffer,
    JobDispute,
    JobCompletionImage,
    ProviderRating,
)
from apps.jobs.mixins import JobRequestMixin, ProviderMixin
from apps.jobs.serializers import (
    JobRequestReadSerializer,
    JobRequestWriteSerializer,
    JobRequestImageSerializer,
    JobCompletionImageSerializer,
    JobConfirmCompletionSerializer,
    JobRequestOfferSerializer,
    JobDisputeSerializer,
    AdminJobDisputeSerializer,
)
from apps.jobs.filters import JobFilter
from apps.jobs.notifications import (
    create_dispute_cancelled_provider_notification,
    create_dispute_opened_admin_notification,
    create_dispute_opened_notification,
    create_dispute_refunded_customer_notification,
    create_dispute_released_customer_notification,
    create_dispute_released_provider_notification,
    create_job_completion_approved_notification,
    create_job_completion_request_notification,
    create_job_created_notification,
    create_job_new_offer_notification,
    create_job_offer_accepted_notification,
    create_job_offer_rejected_notification,
    create_job_updated_notification,
    create_job_cancelled_notification,
)  # , send_job_created_email

from apps.konnett_points.utils import (
    pay_provider,
    reserve_job_points,
    adjust_reserved_points,
    release_reserved_points,
)

from apps.mails.services import create_mailbox_message

# Create your views here.


class JobRequestViewSet(JobRequestMixin, viewsets.ModelViewSet):
    http_method_names = ["post", "get", "patch", "delete"]
    parser_classes = [MultiPartParser, FormParser]

    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]

    filterset_class = JobFilter
    search_fields = ["title", "description"]
    ordering_fields = ["created_at", "points_amount"]
    throttle_scope = "job_mutations"

    # ^ get_queryset retrieves the queryset of JobRequest instances based on the authenticated user's role.
    # If the user is a staff member, all job requests are returned.
    # If the user is a customer, only their own job requests are returned.
    # If the user is a provider, only pending job requests are returned.
    def get_queryset(self):
        offer_queryset = JobRequestOffer.objects.select_related(
            "provider",
            "job",
        )

        dispute_queryset = JobDispute.objects.select_related(
            "job",
            "job__customer",
        )

        queryset = JobRequest.objects.select_related(
            "customer",
            "customer__user",
            "category",
            "primary_location",
            "secondary_location",
        ).prefetch_related(
            "job_request_images",
            "job_completion_images",
            Prefetch(
                "job_offers",
                queryset=offer_queryset,
            ),
            Prefetch(
                "dispute",
                queryset=dispute_queryset,
            ),
        )

        user = self.request.user

        if user.is_staff:
            return queryset

        if hasattr(user, "customer_profile"):
            return queryset.filter(customer=user.customer_profile)

        if hasattr(user, "provider_profile"):
            return queryset.filter(status=JobRequestStatus.PENDING)

        return queryset.none()

    def get_serializer_class(self):
        if self.action in ["create", "partial_update"]:
            return JobRequestWriteSerializer

        return JobRequestReadSerializer

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            permission = IsCustomer | IsVerifiedProvider | IsAdminUser
            return [permission()]

        elif self.action in ["partial_update", "destroy"]:
            return [IsCustomerOwner()]

        return [IsCustomer()]

    def get_throttles(self):
        if self.action in ["list", "retrieve"]:
            if self.request.user.is_authenticated:
                return [UserRateThrottle()]
            else:
                return [AnonRateThrottle()]

        if self.action in ["create", "partial_update", "destroy"]:
            return [ScopedRateThrottle()]

        return super().get_throttles()

    @transaction.atomic
    def perform_create(self, serializer):
        images = serializer.validated_data.pop("images", [])

        job = serializer.save(customer=self.request.user.customer_profile)

        JobRequestImage.objects.bulk_create(
            [
                JobRequestImage(
                    job=job,
                    image=image,
                )
                for image in images
            ]
        )

        reserve_job_points(job)

        # Notify customer
        # -- BACKGROUND TASK
        transaction.on_commit(
            lambda: create_job_created_notification(user=self.request.user, job=job)
        )

    # ^ partial_update updates a job request instance.
    # It ensures that the job is still pending before allowing the update.
    # If the job is not pending, an error message is returned.
    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        job = self.get_object()
        self.ensure_job_is_pending(job, "This job can no longer be edited.")

        old_points_amount = job.points_amount

        response = super().partial_update(request, *args, **kwargs)

        job.refresh_from_db(fields=["points_amount"])

        if job.points_amount != old_points_amount:
            adjust_reserved_points(job, old_points_amount)

        # Notify customer of job update
        # -- BACKGROUND TASK
        transaction.on_commit(
            lambda: create_job_updated_notification(user=self.request.user, job=job)
        )

        return response

    # ^ destroy cancels a job request instance.
    # It ensures that the job is still pending or open before allowing the cancellation.
    # If the job is not in one of these states, an error message is returned.
    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        job = self.get_object()
        self.ensure_job_is_pending_or_open(job)

        job.status = JobRequestStatus.CANCELLED
        job.save(update_fields=["status"])

        release_reserved_points(job, transaction_type=TransactionType.UNLOCK)

        # Notify the customer and all providers who made offers.
        # -- BACKGROUND TASK
        users = [job.customer.user]
        # extend() adds individual elements from an iterable (in this case, the providers' users) to the end of the list (users).
        users.extend(
            offer.provider.user
            for offer in job.job_offers.select_related("provider__user").all()
        )
        transaction.on_commit(
            lambda: create_job_cancelled_notification(
                users=users,
                job=job,
            )
        )

        return Response(status=status.HTTP_204_NO_CONTENT)


class JobRequestImageCreateView(JobRequestMixin, generics.CreateAPIView):
    serializer_class = JobRequestImageSerializer
    permission_classes = [IsCustomer]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "job_images"

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        job = get_object_or_404(
            JobRequest.objects.select_for_update().select_related(
                "customer",
                "customer__user",
            ),
            pk=self.kwargs["pk"],
        )

        self.check_job_owner(job)
        self.ensure_job_is_pending(job)

        current_image_count = job.job_request_images.count()

        if current_image_count >= MAX_JOB_REQUEST_IMAGES:
            return Response(
                {
                    "detail": (
                        f"Maximum of {MAX_JOB_REQUEST_IMAGES} "
                        "images allowed for this job."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(
            data=request.data,
            context={"job": job},
        )
        serializer.is_valid(raise_exception=True)

        serializer.save(job=job)

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


class JobRequestImageDeleteView(JobRequestMixin, APIView):
    permission_classes = [IsCustomer]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "job_images"

    http_method_names = ["delete"]

    @extend_schema(
        request=None,
        responses={
            204: OpenApiResponse(description="Image deleted successfully."),
        },
    )
    def delete(self, request, *args, **kwargs):
        image = get_object_or_404(
            JobRequestImage.objects.select_related(
                "job",
                "job__customer",
                "job__customer__user",
            ),
            pk=kwargs["pk"],
        )

        job = image.job

        self.check_job_owner(job)
        self.ensure_job_is_pending(job)

        image.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


class JobOfferView(JobRequestMixin, generics.ListCreateAPIView):
    serializer_class = JobRequestOfferSerializer
    throttle_scope = "job_offers"

    # get_permissions returns the appropriate permissions based on the request method and whether a specific job ID is provided in the URL.
    # For GET requests without a job ID, only verified providers can access the endpoint.
    def get_permissions(self):
        if self.request.method == "GET":
            if "pk" not in self.kwargs:
                return [IsVerifiedProvider()]

            permission = IsCustomer | IsVerifiedProvider
            return [permission()]

        return [IsVerifiedProvider()]

    # get_queryset returns the appropriate queryset based on the request method and whether a specific job ID is provided in the URL.
    # For GET requests without a job ID, only verified providers can access the endpoint.
    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return JobRequestOffer.objects.none()

        # Provider endpoint: /provider/offers/
        if "pk" not in self.kwargs:
            return (
                JobRequestOffer.objects.filter(
                    provider=self.request.user.provider_profile,
                )
                .select_related("provider", "job__customer")
                .order_by("status", "-created_at")
            )

        # Customer endpoint: /jobs/<job_id>/offers/
        job = self.get_job()
        self.check_job_owner(job)

        return (
            JobRequestOffer.objects.filter(job=job)
            .select_related("provider", "job__customer")
            .order_by("-created_at")
        )

    def get_throttles(self):
        if self.request.method == "GET":
            return [UserRateThrottle()]
        return [ScopedRateThrottle()]

    def create(self, request, *args, **kwargs):
        # Provider's get request doesn't have a job_id
        # This disables the provider from sending a post request w/o including a job_id
        if "pk" not in self.kwargs:
            return Response(
                {"detail": "Offers can only be created for a specific job."},
                status=status.HTTP_405_METHOD_NOT_ALLOWED,
            )

        job = self.get_job()
        self.ensure_job_is_pending_or_open(
            job, "This job is no longer accepting offers."
        )

        # Check if the provider has already submitted an offer for this job.
        if JobRequestOffer.objects.filter(
            job=job,
            provider=request.user.provider_profile,
        ).exists():
            return Response(
                {"detail": "You have already submitted an offer for this job."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            job=job,
            provider=request.user.provider_profile,
        )

        # -- BACKGROUND TASK
        # Notify the job owner, of a new offer
        transaction.on_commit(
            lambda: create_job_new_offer_notification(user=job.customer.user, job=job)
        )

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


class JobOfferAcceptView(JobRequestMixin, ProviderMixin, APIView):
    permission_classes = [IsCustomer]
    http_method_names = ["patch"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "job_offer_actions"

    # transaction.atomic ensures that the entire operation is treated as a single transaction.
    # If any part of the operation fails, the entire transaction will be rolled back, ensuring data integrity.
    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(description="Offer accepted."),
        },
    )
    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        # Get the job ID associated with this offer.
        initial_offer = get_object_or_404(
            JobRequestOffer.objects.only("pk", "job_id"),
            pk=self.kwargs["pk"],
        )

        # Lock the job row.
        # Other acceptance requests for this same job must wait until this transaction finishes.
        job = get_object_or_404(
            JobRequest.objects.select_for_update(),
            pk=initial_offer.job_id,
        )

        # Re-fetch and lock the offer after acquiring the job lock.
        offer = get_object_or_404(
            JobRequestOffer.objects.select_for_update().select_related(
                "provider__user",
            ),
            pk=self.kwargs["pk"],
            job=job,
        )

        # Perform these checks AFTER acquiring the locks.
        self.check_job_owner(job)

        self.ensure_job_is_open(
            job,
            "Offers can only be managed while the job is open",
        )

        self.ensure_offer_is_pending(
            offer,
            "This offer has already been processed.",
        )

        # Accept this offer.
        offer.status = JobOfferStatus.ACCEPTED
        offer.save(update_fields=["status"])

        # Reject all other pending offers for this job.
        JobRequestOffer.objects.filter(
            job=job,
            status=JobOfferStatus.PENDING,
        ).exclude(
            pk=offer.pk,
        ).update(
            status=JobOfferStatus.REJECTED,
        )

        # Mark the job as in progress.
        job.status = JobRequestStatus.IN_PROGRESS
        job.save(update_fields=["status"])

        # -- BACKGROUND TASK
        # Notify the accepted provider after commit.
        transaction.on_commit(
            lambda: create_job_offer_accepted_notification(
                user=offer.provider.user,
                job=job,
            )
        )

        # -- BACKGROUND TASK
        # Notify rejected providers.
        rejected_offers = (
            JobRequestOffer.objects.filter(
                job=job,
                status=JobOfferStatus.REJECTED,
            )
            .exclude(pk=offer.pk)
            .select_related("provider__user")
        )

        for rejected_offer in rejected_offers:
            transaction.on_commit(
                lambda user=rejected_offer.provider.user: (
                    create_job_offer_rejected_notification(
                        user=user,
                        job=job,
                    )
                )
            )

        return Response(
            {"detail": "Offer accepted."},
            status=status.HTTP_200_OK,
        )


class JobOfferRejectView(JobRequestMixin, ProviderMixin, APIView):
    permission_classes = [IsCustomer]
    http_method_names = ["patch"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "job_offer_actions"

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(description="Offer rejected."),
        },
    )
    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        offer = get_object_or_404(
            JobRequestOffer.objects.select_related(
                "job",
                "job__customer",
                "job__customer__user",
            ),
            pk=self.kwargs["pk"],
        )
        job = offer.job

        self.check_job_owner(job)
        self.ensure_job_is_open(
            job,
            "You can only reject offers while the job is open.",
        )

        self.ensure_offer_is_pending(offer, "This offer has already been processed.")

        offer.status = JobOfferStatus.REJECTED
        offer.save(update_fields=["status"])

        # -- BACKGROUND TASK
        # Notify rejected provider
        transaction.on_commit(
            lambda: create_job_offer_rejected_notification(
                user=offer.provider.user,
                job=job,
            )
        )

        return Response(
            {"detail": "Offer rejected."},
            status=status.HTTP_200_OK,
        )


class JobOfferWithdrawView(ProviderMixin, JobRequestMixin, APIView):
    permission_classes = [IsVerifiedProvider]
    http_method_names = ["patch"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "job_offer_actions"

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(description="Offer withdrawn."),
        },
    )
    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        offer = get_object_or_404(
            JobRequestOffer.objects.select_related(
                "job",
                "job__customer",
                "job__customer__user",
                "provider",
            ),
            pk=self.kwargs["pk"],
        )
        job = offer.job

        self.check_offer_owner(offer)
        self.ensure_job_is_open(job, "You can only withdraw offers from open jobs.")

        self.ensure_offer_is_pending(offer, "Only pending offers can be withdrawn.")

        offer.status = JobOfferStatus.WITHDRAWN
        offer.save(update_fields=["status"])

        return Response(
            {"detail": "Offer withdrawn."},
            status=status.HTTP_200_OK,
        )


class JobCompletionImageCreateView(
    JobRequestMixin, ProviderMixin, generics.CreateAPIView
):
    serializer_class = JobCompletionImageSerializer
    permission_classes = [IsVerifiedProvider]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "job_images"

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        job = self.get_job()

        self.ensure_job_is_in_progress(
            job,
            "Completion images can only be uploaded while the job is in progress.",
        )

        offer = self.check_accepted_provider(job)

        images = request.FILES.getlist("images")

        if not images:
            return Response(
                {"images": "At least one image is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing_count = job.job_completion_images.count()

        if existing_count + len(images) > MAX_JOB_COMPLETION_IMAGES:
            remaining = MAX_JOB_COMPLETION_IMAGES - existing_count

            return Response(
                {
                    "images": (
                        f"You can upload a maximum of {MAX_JOB_COMPLETION_IMAGES} "
                        f"completion images per job. "
                        f"You can upload {max(remaining, 0)} more."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(data={"images": images})
        serializer.is_valid(raise_exception=True)

        JobCompletionImage.objects.bulk_create(
            [
                JobCompletionImage(
                    job=job,
                    provider=offer.provider,
                    image=image,
                )
                for image in serializer.validated_data["images"]
            ]
        )

        return Response(
            {"detail": f"{len(images)} completion image(s) uploaded successfully."},
            status=status.HTTP_201_CREATED,
        )


class JobRequestCompletionView(JobRequestMixin, ProviderMixin, APIView):
    permission_classes = [IsVerifiedProvider]
    http_method_names = ["patch"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "job_completion"

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(description="Completion request sent successfully.")
        },
    )
    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        job = self.get_job()

        self.ensure_job_is_in_progress(
            job, "Only the jobs in progress can request completion"
        )
        self.check_accepted_provider(job)

        # Ensure that at least one completion image has been uploaded before allowing the provider to request completion.
        if not job.job_completion_images.exists():
            return Response(
                {
                    "detail": (
                        "Upload at least one completion image "
                        "before requesting completion."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        job.status = JobRequestStatus.AWAITING_CONFIRMATION
        job.save(update_fields=["status"])

        # -- BACKGROUND TASK
        # Notify job owner of a completion request
        transaction.on_commit(
            lambda: create_job_completion_request_notification(
                user=job.customer.user,
                job=job,
            )
        )

        return Response(
            {"detail": ("Completion request sent successfully.")},
            status=status.HTTP_200_OK,
        )


class JobConfirmCompletionView(JobRequestMixin, APIView):
    permission_classes = [IsCustomer]
    http_method_names = ["patch"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "job_completion"

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(description="Job completed successfully."),
        },
    )
    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        job = get_object_or_404(
            JobRequest.objects.select_for_update().select_related(
                "customer",
                "customer__user",
                "customer__user__point_wallet",
            ),
            pk=self.kwargs["pk"],
        )

        self.check_job_owner(job)
        self.ensure_job_is_awaiting_confirmation(
            job, "Only the jobs awaiting completion can be completed"
        )

        serializer = JobConfirmCompletionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        offer = JobRequestOffer.objects.select_related(
            "provider",
            "provider__user",
        ).get(
            job=job,
            status=JobOfferStatus.ACCEPTED,
        )

        provider = offer.provider

        # Create the rating for this completed job.
        ProviderRating.objects.create(
            job=job,
            provider=provider,
            customer=job.customer,
            rating=serializer.validated_data["rating"],
        )

        # Recalculate the provider's average rating.
        average_rating = (
            ProviderRating.objects.filter(provider=provider).aggregate(
                average=Avg("rating")
            )["average"]
            or 0
        )

        # Update provider rating statistics.
        provider.average_rating = average_rating
        provider.ratings_count = ProviderRating.objects.filter(
            provider=provider
        ).count()
        provider.completed_jobs = F("completed_jobs") + 1
        provider.save(
            update_fields=[
                "average_rating",
                "ratings_count",
                "completed_jobs",
            ]
        )

        job.status = JobRequestStatus.COMPLETED
        job.save(update_fields=["status"])

        pay_provider(job, offer)

        # -- BACKGROUND TASK
        # Notify provider of completed job
        transaction.on_commit(
            lambda: create_job_completion_approved_notification(
                user=provider.user,
                job=job,
            )
        )

        return Response(
            {
                "detail": "Job completed successfully.",
                "rating": serializer.validated_data["rating"],
                "provider_average_rating": provider.average_rating,
                "provider_ratings_count": provider.ratings_count,
            },
            status=status.HTTP_200_OK,
        )


class JobDisputeCreateView(JobRequestMixin, generics.CreateAPIView):
    serializer_class = JobDisputeSerializer
    permission_classes = [IsCustomer]
    http_method_names = ["post"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "disputes"

    # create() handles the creation of a new dispute for a specific job.
    # It ensures that the job is still awaiting confirmation before allowing the creation of a dispute.
    @transaction.atomic
    def create(self, request, *args, **kwargs):
        job = get_object_or_404(
            JobRequest.objects.select_for_update().select_related(
                "customer",
                "customer__user",
            ),
            pk=self.kwargs["pk"],
        )
        # Get the provider who accepted the job.
        accepted_offer = get_object_or_404(
            JobRequestOffer.objects.select_related("provider__user"),
            job=job,
            status=JobOfferStatus.ACCEPTED,
        )
        self.check_job_owner(job)

        self.ensure_job_is_awaiting_confirmation(
            job, "Only the jobs awaiting confirmation can be disputed."
        )

        # Check if a dispute already exists for this job.
        if hasattr(job, "dispute"):
            return Response(
                {"detail": "A dispute already exists for this job."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        serializer.save(job=job)

        # Mark the job as disputed.
        job.status = JobRequestStatus.DISPUTED
        job.save(update_fields=["status"])

        # -- BACKGROUND TASK
        # Notify the provider after the transaction commits.
        transaction.on_commit(
            lambda: create_dispute_opened_notification(
                user=accepted_offer.provider.user,
                job=job,
            )
        )

        # -- BACKGROUND TASK
        # Notify administrators after the transaction commits.
        admin_users = User.objects.filter(
            role=UserRole.ADMIN,
            is_active=True,
        )

        for admin in admin_users:
            transaction.on_commit(
                lambda user=admin: create_dispute_opened_admin_notification(
                    user=user,
                    job=job,
                )
            )

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


class JobDisputeDetailView(JobRequestMixin, generics.RetrieveAPIView):
    serializer_class = JobDisputeSerializer
    permission_classes = [IsCustomer | IsAdminUser]
    throttle_classes = [UserRateThrottle]
    queryset = JobDispute.objects.select_related(
        "job",
        "job__customer",
    )

    def get_object(self):
        dispute = super().get_object()

        if self.request.user.is_staff:
            return dispute

        self.check_dispute_owner(dispute)

        return dispute


class AdminResolveDisputeView(JobRequestMixin, generics.UpdateAPIView):
    serializer_class = AdminJobDisputeSerializer
    permission_classes = [IsAdminUser]
    http_method_names = ["patch"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "disputes"

    def get_queryset(self):
        return JobDispute.objects.select_for_update().select_related(
            "job",
            "job__customer",
        )

    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        dispute = self.get_object()

        self.ensure_dispute_is_unresolved(dispute)

        serializer = self.get_serializer(
            dispute,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        dispute = serializer.save(resolved_by=request.user)
        job = dispute.job

        # Get the provider who accepted the job.
        offer = JobRequestOffer.objects.select_related(
            "provider",
            "provider__user",
        ).get(
            job=job,
            status=JobOfferStatus.ACCEPTED,
        )

        customer_user = job.customer.user
        provider_user = offer.provider.user

        if dispute.decision == JobDisputeDecision.REFUND_POINTS:
            job.status = JobRequestStatus.CANCELLED

            release_reserved_points(
                job,
                transaction_type=TransactionType.REFUND,
            )

            # -- BACKGROUND TASK
            # Notify the customer after the transaction commits.
            transaction.on_commit(
                lambda: create_dispute_refunded_customer_notification(
                    user=customer_user,
                    job=job,
                )
            )

            # -- BACKGROUND TASK
            # Notify the provider after the transaction commits.
            transaction.on_commit(
                lambda: create_dispute_cancelled_provider_notification(
                    user=provider_user,
                    job=job,
                )
            )

        elif dispute.decision == JobDisputeDecision.RELEASE_POINTS:
            job.status = JobRequestStatus.COMPLETED

            pay_provider(job, offer)

            offer.provider.completed_jobs = F("completed_jobs") + 1
            offer.provider.save(update_fields=["completed_jobs"])

            # -- BACKGROUND TASK
            # Notify the customer after the transaction commits.
            transaction.on_commit(
                lambda: create_dispute_released_customer_notification(
                    user=customer_user,
                    job=job,
                )
            )

            # -- BACKGROUND TASK
            # Notify the provider after the transaction commits.
            transaction.on_commit(
                lambda: create_dispute_released_provider_notification(
                    user=provider_user,
                    job=job,
                )
            )

        job.save(update_fields=["status"])

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )
