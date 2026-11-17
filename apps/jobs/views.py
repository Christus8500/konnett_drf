import logging

from django.db import transaction
from django.db.models import F, Q, Count, Prefetch, Avg
from django.utils import timezone
from django.shortcuts import get_object_or_404

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import viewsets, generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.exceptions import ValidationError
from rest_framework.throttling import (
    ScopedRateThrottle,
    UserRateThrottle,
    AnonRateThrottle,
)

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)

from apps.core.permissions import (
    IsCustomer,
    IsCustomerOwner,
    IsProvider,
    IsVerifiedProvider,
)
from apps.core.choices import (
    JobRequestStatus,
    JobOfferStatus,
    JobDisputeDecision,
    TransactionType,
    UserRole,
)
from apps.core.constants import MAX_JOB_COMPLETION_IMAGES, MAX_JOB_REQUEST_IMAGES
from apps.core.utils import FORBIDDEN, THROTTLED, UNAUTHORIZED

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
    JobCompletionConfirmedResponseSerializer,
    JobRequestReadSerializer,
    JobRequestWriteSerializer,
    JobRequestImageSerializer,
    JobCompletionImageSerializer,
    JobConfirmCompletionSerializer,
    JobRequestOfferSerializer,
    JobDisputeSerializer,
    AdminJobDisputeSerializer,
    JobsDetailResponseSerializer,
    ProviderRatingSerializer,
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
)

from apps.konnett_points.utils import (
    pay_provider,
    reserve_job_points,
    adjust_reserved_points,
    release_reserved_points,
)

from apps.providers.models import ProviderProfile
 
logger = logging.getLogger(__name__)

def _detail(description):
    return OpenApiResponse(response=JobsDetailResponseSerializer, description=description)


def _path_uuid(name, description):
    return OpenApiParameter(
        name=name,
        type=OpenApiTypes.UUID,
        location=OpenApiParameter.PATH,
        description=description,
    )



JOB_ID = _path_uuid("pk", "Job ID.")
OFFER_ID = _path_uuid("pk", "Offer ID.")
IMAGE_ID = _path_uuid("pk", "Image ID.")
PROVIDER_ID = _path_uuid("provider_id", "Provider profile ID.")

JOB_NOT_FOUND = OpenApiResponse(description="Job not found.")
OFFER_NOT_FOUND = OpenApiResponse(description="Offer not found.")
# The mixins raise ValidationError("message") with a bare string, which DRF
# renders as a JSON ARRAY of messages, not {"detail": ...}. Explicit
# Response/dict errors in the views use {"detail": "..."}.
STATE_ERROR_NOTE = (
    ' State errors (wrong job/offer status) are returned as a JSON array of '
    'messages, e.g. ["This job is not open."]; other failures use {"detail": "..."}.'
)
BAD_STATE = OpenApiResponse(
    description="The job or offer is not in a state that allows this action." + STATE_ERROR_NOTE
)
NOT_ALLOWED = OpenApiResponse(
    response=JobsDetailResponseSerializer,
    description=(
        "Wrong role, or you do not own this job, offer or dispute "
        '(e.g. {"detail": "You do not own this job."}).'
    ),
)

# Create your views here.



@extend_schema_view(
    list=extend_schema(
        tags=["Jobs"],
        summary="List jobs",
        description=(
            "Staff see all jobs. Customers see their own. Verified providers see "
            "pending and open jobs plus the jobs they were accepted for. Supports "
            "the filter query parameters, `search` (title, description) and "
            "`ordering` (`created_at`, `points_amount`). Paginated."
        ),
        responses={
            200: JobRequestReadSerializer,
            401: UNAUTHORIZED,
            403: NOT_ALLOWED,
            429: THROTTLED,
        },
    ),
    retrieve=extend_schema(
        tags=["Jobs"],
        summary="Get a job",
        responses={
            200: JobRequestReadSerializer,
            401: UNAUTHORIZED,
            403: NOT_ALLOWED,
            404: JOB_NOT_FOUND,
            429: THROTTLED,
        },
    ),
    create=extend_schema(
        tags=["Jobs"],
        summary="Create a job (customers)",
        description=(
            "multipart/form-data, with optional `images`. Reserves the job's points "
            "from the customer's wallet."
        ),
        request=JobRequestWriteSerializer,
        responses={
            201: JobRequestWriteSerializer,
            400: OpenApiResponse(
                description="Validation error, e.g. insufficient available points."
            ),
            401: UNAUTHORIZED,
            403: NOT_ALLOWED,
            429: THROTTLED,
        },
    ),
    partial_update=extend_schema(
        tags=["Jobs"],
        summary="Update a job (owner, pending only)",
        description="Adjusts the reserved points if `points_amount` changes.",
        request=JobRequestWriteSerializer,
        responses={
            200: JobRequestWriteSerializer,
            400: OpenApiResponse(
                description=("Validation error, or the job can no longer be edited." + STATE_ERROR_NOTE)
            ),
            401: UNAUTHORIZED,
            403: NOT_ALLOWED,
            404: JOB_NOT_FOUND,
            429: THROTTLED,
        },
    ),
    destroy=extend_schema(
        tags=["Jobs"],
        summary="Cancel a job (owner, pending or open only)",
        description="Releases the reserved points and rejects all pending offers.",
        responses={
            204: OpenApiResponse(description="Job cancelled."),
            400: BAD_STATE,
            401: UNAUTHORIZED,
            403: NOT_ALLOWED,
            404: JOB_NOT_FOUND,
            429: THROTTLED,
        },
    ),
)
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
            "job__customer__user",
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
            own_job_ids = JobRequestOffer.objects.filter(
                provider=user.provider_profile,
                status=JobOfferStatus.ACCEPTED,
            ).values("job_id")

            return queryset.filter(
                Q(status__in=[JobRequestStatus.PENDING, JobRequestStatus.OPEN])
                | Q(pk__in=own_job_ids)
            )

        return queryset.none()

    def get_object(self):
        if self.action in ("partial_update", "destroy"):
            obj = get_object_or_404(
                self.get_queryset().select_for_update(of=("self",)),
                pk=self.kwargs["pk"],
            )
            self.check_object_permissions(self.request, obj)
            return obj
        return super().get_object()

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
        transaction.on_commit(
            lambda: create_job_created_notification(
                user=self.request.user, job=job)
        )

        logger.info(
            "Job created user_id=%s job_id=%s points=%s images=%s",
            self.request.user.pk,
            job.pk,
            job.points_amount,
            len(images),
        )

    @transaction.atomic
    def perform_update(self, serializer):
        images = serializer.validated_data.pop("images", [])
        job = serializer.save()

        JobRequestImage.objects.bulk_create(
            [JobRequestImage(job=job, image=image) for image in images]
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
        transaction.on_commit(
            lambda: create_job_updated_notification(
                user=self.request.user, job=job)
        )

        logger.info(
            "Job updated user_id=%s job_id=%s points_changed=%s",
            request.user.pk,
            job.pk,
            job.points_amount != old_points_amount,
        )

        return response

    # ^ destroy cancels a job request instance.
    # It ensures that the job is still pending or open before allowing the cancellation.
    # If the job is not in one of these states, an error message is returned.
    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        job = self.get_object()
        self.ensure_job_is_pending_or_open(job)

        # Capture live offers BEFORE changing anything.
        pending_offers = list(
            job.job_offers.select_related("provider__user").filter(
                status=JobOfferStatus.PENDING
            )
        )

        job.status = JobRequestStatus.CANCELLED
        job.save(update_fields=["status", "updated_at"])

        release_reserved_points(job, transaction_type=TransactionType.UNLOCK)

        JobRequestOffer.objects.filter(pk__in=[o.pk for o in pending_offers]).update(
            status=JobOfferStatus.REJECTED
        )

        # Notify the customer and all providers whose offers are still pending.
        # -- If you think users might be around 200, consider moving to celery
        users = [job.customer.user] + [o.provider.user for o in pending_offers]
        transaction.on_commit(
            lambda: create_job_cancelled_notification(users=users, job=job)
        )

        logger.info(
            "Job cancelled by customer user_id=%s job_id=%s pending_offers_rejected=%s",
            request.user.pk,
            job.pk,
            len(pending_offers),
        )

        return Response(status=status.HTTP_204_NO_CONTENT)


# (Decorator is on the class: spectacular reads the post handler, not create().)
@extend_schema(
    tags=["Jobs"],
    summary="Add an image to a pending job (owner)",
    description="multipart/form-data. Limited to a maximum number of images per job.",
    parameters=[JOB_ID],
    request=JobRequestImageSerializer,
    responses={
        201: JobRequestImageSerializer,
        400: OpenApiResponse(
            description=("Validation error, image limit reached, or the job is not pending." + STATE_ERROR_NOTE)
        ),
        401: UNAUTHORIZED,
        403: NOT_ALLOWED,
        404: JOB_NOT_FOUND,
        429: THROTTLED,
    },
)
class JobRequestImageCreateView(JobRequestMixin, generics.CreateAPIView):
    serializer_class = JobRequestImageSerializer
    permission_classes = [IsCustomer]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "job_images"

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        job = self.get_locked_job()

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

        logger.info(
            "Job image added user_id=%s job_id=%s image_id=%s",
            request.user.pk,
            job.pk,
            serializer.instance.pk,
        )

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
        tags=["Jobs"],
        summary="Delete an image from a pending job (owner)",
        parameters=[IMAGE_ID],
        request=None,
        responses={
            204: OpenApiResponse(description="Image deleted successfully."),
            400: BAD_STATE,
            401: UNAUTHORIZED,
            403: NOT_ALLOWED,
            404: OpenApiResponse(description="Image not found."),
            429: THROTTLED,
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


# NOTE: this one view serves two routes (/provider/offers/ and /jobs/<id>/offers/),
# so the generated schema lists both. Splitting it into two classes would give
# each route its own accurate documentation.
@extend_schema_view(
    get=extend_schema(
        tags=["Offers"],
        summary="List offers",
        description=(
            "Without a job ID (provider route): the verified provider's own offers. "
            "With a job ID: the offers on that job, for the job's owner. Paginated."
        ),
        parameters=[
            OpenApiParameter(
                name="pk",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                required=False,
                description="Job ID (only on the job route).",
            )
        ],
        responses={
            200: JobRequestOfferSerializer,
            401: UNAUTHORIZED,
            403: NOT_ALLOWED,
            404: JOB_NOT_FOUND,
            429: THROTTLED,
        },
    ),
    post=extend_schema(
        tags=["Offers"],
        summary="Make an offer on a job (verified providers)",
        description=(
            "Only valid on the job route. Re-offering after withdrawing reuses the "
            "withdrawn offer."
        ),
        parameters=[
            OpenApiParameter(
                name="pk",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                required=False,
                description="Job ID.",
            )
        ],
        request=JobRequestOfferSerializer,
        responses={
            201: JobRequestOfferSerializer,
            400: OpenApiResponse(
                description=((
                    "Validation error, job not accepting offers, deadline passed, "
                    "or an offer already exists."
                ) + STATE_ERROR_NOTE)
            ),
            401: UNAUTHORIZED,
            403: NOT_ALLOWED,
            404: JOB_NOT_FOUND,
            405: _detail("Called without a job ID."),
            429: THROTTLED,
        },
    ),
)
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
    # For GET requests with a job ID, the authenticated customer must own the job to access the offers.
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

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        # Provider's get request doesn't have a job_id
        # This disables the provider from sending a post request w/o including a job_id
        if "pk" not in self.kwargs:
            return Response(
                {"detail": "Offers can only be created for a specific job."},
                status=status.HTTP_405_METHOD_NOT_ALLOWED,
            )

        job = self.get_locked_job()
        self.ensure_job_is_pending_or_open(
            job, "This job is no longer accepting offers."
        )

        if job.deadline is not None and job.deadline <= timezone.now():
            raise ValidationError(
                {"detail": "This job's deadline has passed."})

        provider = request.user.provider_profile

        existing = (
            JobRequestOffer.objects.select_for_update(of=("self",))
            .filter(job=job, provider=provider)
            .first()
        )

        if existing is None:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            offer = serializer.save(job=job, provider=provider)
            data = serializer.data
        elif existing.status == JobOfferStatus.WITHDRAWN:
            # Re-offer: reuse the withdrawn row (the unique constraint allows only one per provider).
            existing.status = JobOfferStatus.PENDING
            # the signal moves the job to OPEN
            existing.save(update_fields=["status", "updated_at"])
            offer = existing
            data = self.get_serializer(existing).data
        else:
            return Response(
                {"detail": "You have already submitted an offer for this job."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        transaction.on_commit(
            lambda: create_job_new_offer_notification(
                user=job.customer.user, job=job)
        )

        logger.info(
            "Offer submitted provider_id=%s job_id=%s offer_id=%s reoffer=%s",
            provider.pk,
            job.pk,
            offer.pk,
            reoffer,
        )

        return Response(data, status=status.HTTP_201_CREATED)


class JobOfferAcceptView(JobRequestMixin, ProviderMixin, APIView):
    permission_classes = [IsCustomer]
    http_method_names = ["patch"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "job_offer_actions"

    @extend_schema(
        tags=["Offers"],
        summary="Accept an offer (job owner)",
        description=(
            "No request body. Moves the job to in-progress and rejects all other "
            "pending offers."
        ),
        parameters=[OFFER_ID],
        request=None,
        responses={
            200: _detail("Offer accepted."),
            400: OpenApiResponse(
                description=((
                    "Job not open, offer already processed, or the job's deadline "
                    "has passed."
                ) + STATE_ERROR_NOTE)
            ),
            401: UNAUTHORIZED,
            403: NOT_ALLOWED,
            404: OFFER_NOT_FOUND,
            429: THROTTLED,
        },
    )
    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        initial_offer = get_object_or_404(
            JobRequestOffer.objects.only("pk", "job_id"),
            pk=self.kwargs["pk"],
        )

        job = get_object_or_404(
            JobRequest.objects.select_for_update(of=("self",)).select_related(
                "customer__user"
            ),
            pk=initial_offer.job_id,
        )
        offer = get_object_or_404(
            JobRequestOffer.objects.select_for_update(of=("self",)).select_related(
                "provider__user"
            ),
            pk=self.kwargs["pk"],
            job=job,
        )

        self.check_job_owner(job)
        self.ensure_job_is_open(
            job, "Offers can only be managed while the job is open")
        self.ensure_offer_is_pending(
            offer, "This offer has already been processed.")

        if job.deadline is not None and job.deadline <= timezone.now():
            raise ValidationError(
                {"detail": "This job's deadline has passed."})

        # Offers about to be rejected (captured BEFORE the update).
        other_offers = list(
            JobRequestOffer.objects.select_related("provider__user")
            .filter(job=job, status=JobOfferStatus.PENDING)
            .exclude(pk=offer.pk)
        )

        offer.status = JobOfferStatus.ACCEPTED
        offer.save(update_fields=["status", "updated_at"])

        JobRequestOffer.objects.filter(pk__in=[o.pk for o in other_offers]).update(
            status=JobOfferStatus.REJECTED
        )

        job.status = JobRequestStatus.IN_PROGRESS
        job.save(update_fields=["status", "updated_at"])

        transaction.on_commit(
            lambda: create_job_offer_accepted_notification(
                user=offer.provider.user, job=job
            )
        )

        for rejected in other_offers:
            transaction.on_commit(
                lambda user=rejected.provider.user: create_job_offer_rejected_notification(
                    user=user, job=job
                )
            )

        logger.info(
            "Offer accepted user_id=%s job_id=%s offer_id=%s others_rejected=%s",
            request.user.pk,
            job.pk,
            offer.pk,
            len(other_offers),
        )

        return Response({"detail": "Offer accepted."}, status=status.HTTP_200_OK)


class JobOfferRejectView(JobRequestMixin, ProviderMixin, APIView):
    permission_classes = [IsCustomer]
    http_method_names = ["patch"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "job_offer_actions"

    @extend_schema(
        tags=["Offers"],
        summary="Reject an offer (job owner)",
        description="No request body. The job returns to pending if no offers are left.",
        parameters=[OFFER_ID],
        request=None,
        responses={
            200: _detail("Offer rejected."),
            400: BAD_STATE,
            401: UNAUTHORIZED,
            403: NOT_ALLOWED,
            404: OFFER_NOT_FOUND,
            429: THROTTLED,
        },
    )
    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        initial_offer = get_object_or_404(
            JobRequestOffer.objects.only("pk", "job_id"),
            pk=self.kwargs["pk"],
        )

        job = get_object_or_404(
            JobRequest.objects.select_for_update(of=("self",)).select_related(
                "customer__user"
            ),
            pk=initial_offer.job_id,
        )
        offer = get_object_or_404(
            JobRequestOffer.objects.select_for_update(of=("self",)).select_related(
                "provider__user"
            ),
            pk=self.kwargs["pk"],
            job=job,
        )

        self.check_job_owner(job)
        self.ensure_job_is_open(
            job, "You can only reject offers while the job is open."
        )
        self.ensure_offer_is_pending(
            offer, "This offer has already been processed.")

        offer.status = JobOfferStatus.REJECTED
        offer.save(
            update_fields=["status", "updated_at"]
        )  # the update_job_status_on_offer_change signal moves the job to PENDING if none are left

        transaction.on_commit(
            lambda: create_job_offer_rejected_notification(
                user=offer.provider.user, job=job
            )
        )

        logger.info(
            "Offer rejected user_id=%s job_id=%s offer_id=%s",
            request.user.pk,
            job.pk,
            offer.pk,
        )

        return Response({"detail": "Offer rejected."}, status=status.HTTP_200_OK)


class JobOfferWithdrawView(ProviderMixin, JobRequestMixin, APIView):
    permission_classes = [IsVerifiedProvider]
    http_method_names = ["patch"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "job_offer_actions"

    @extend_schema(
        tags=["Offers"],
        summary="Withdraw my offer (provider)",
        description="No request body. Only pending offers on open jobs can be withdrawn.",
        parameters=[OFFER_ID],
        request=None,
        responses={
            200: _detail("Offer withdrawn."),
            400: BAD_STATE,
            401: UNAUTHORIZED,
            403: NOT_ALLOWED,
            404: OFFER_NOT_FOUND,
            429: THROTTLED,
        },
    )
    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        initial_offer = get_object_or_404(
            JobRequestOffer.objects.only("pk", "job_id"),
            pk=self.kwargs["pk"],
        )

        # Lock order everywhere: job first, then offer.
        job = get_object_or_404(
            JobRequest.objects.select_for_update(of=("self",)),
            pk=initial_offer.job_id,
        )
        offer = get_object_or_404(
            JobRequestOffer.objects.select_for_update(of=("self",)).select_related(
                "provider__user"
            ),
            pk=self.kwargs["pk"],
            job=job,
        )

        self.check_offer_owner(offer)
        self.ensure_job_is_open(
            job, "You can only withdraw offers from open jobs.")
        self.ensure_offer_is_pending(
            offer, "Only pending offers can be withdrawn.")

        # The post_save signal moves the job back to PENDING if this was the last pending offer.
        offer.status = JobOfferStatus.WITHDRAWN
        offer.save(update_fields=["status", "updated_at"])

        logger.info(
            "Offer withdrawn user_id=%s job_id=%s offer_id=%s",
            request.user.pk,
            job.pk,
            offer.pk,
        )

        return Response({"detail": "Offer withdrawn."}, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Jobs"],
    summary="Upload completion images (accepted provider)",
    description=(
        "multipart/form-data with one or more `images`. Only while the job is in "
        "progress. Limited to a maximum number of completion images per job."
    ),
    parameters=[JOB_ID],
    request=JobCompletionImageSerializer,
    responses={
        201: _detail("N completion image(s) uploaded successfully."),
        400: OpenApiResponse(
            description=("No images, too many images, invalid image, or the job is not in progress." + STATE_ERROR_NOTE)
        ),
        401: UNAUTHORIZED,
        403: NOT_ALLOWED,
        404: JOB_NOT_FOUND,
        429: THROTTLED,
    },
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

        logger.info(
            "Completion images uploaded user_id=%s job_id=%s count=%s",
            request.user.pk,
            job.pk,
            len(images),
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
        tags=["Jobs"],
        summary="Request completion confirmation (accepted provider)",
        description=(
            "No request body. Requires at least one completion image and a job that "
            "is in progress and not past its deadline."
        ),
        parameters=[JOB_ID],
        request=None,
        responses={
            200: _detail("Completion request sent successfully."),
            400: OpenApiResponse(
                description=((
                    "Job not in progress, no completion image uploaded, or the "
                    "deadline has passed."
                ) + STATE_ERROR_NOTE)
            ),
            401: UNAUTHORIZED,
            403: NOT_ALLOWED,
            404: JOB_NOT_FOUND,
            429: THROTTLED,
        },
    )
    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        job = self.get_locked_job()

        self.ensure_job_is_in_progress(
            job, "Only the jobs in progress can request completion"
        )
        self.check_accepted_provider(job)

        # After the deadline, Celery settles the job. 
        # Without this check a provider could submit late and be paid in full instead of the partial percentage.
        if job.deadline is not None and job.deadline <= timezone.now():
            raise ValidationError(
                {"detail": "The deadline has passed. This job will be settled automatically."}
            )

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
        job.save(update_fields=["status", "updated_at"])

        # Notify job owner of a completion request
        transaction.on_commit(
            lambda: create_job_completion_request_notification(
                user=job.customer.user,
                job=job,
            )
        )

        logger.info(
            "Completion requested user_id=%s job_id=%s", request.user.pk, job.pk
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
        tags=["Jobs"],
        summary="Confirm completion and rate the provider (job owner)",
        description=(
            "Records the rating, updates the provider's rating statistics and "
            "releases payment to the provider."
        ),
        parameters=[JOB_ID],
        request=JobConfirmCompletionSerializer,
        responses={
            200: JobCompletionConfirmedResponseSerializer,
            400: OpenApiResponse(
                description=("Validation error, or the job is not awaiting confirmation." + STATE_ERROR_NOTE)
            ),
            401: UNAUTHORIZED,
            403: NOT_ALLOWED,
            404: JOB_NOT_FOUND,
            429: THROTTLED,
        },
    )
    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        job = self.get_locked_job()

        self.check_job_owner(job)
        self.ensure_job_is_awaiting_confirmation(
            job, "Only the jobs awaiting completion can be completed"
        )

        serializer = JobConfirmCompletionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rating_value = serializer.validated_data["rating"]
        comment = serializer.validated_data.get("comment", "")

        offer = get_object_or_404(
            JobRequestOffer.objects.select_related("provider__user"),
            job=job,
            status=JobOfferStatus.ACCEPTED,
        )

        # Lock the provider row so concurrent ratings can't overwrite each other's stats.
        provider = (
            ProviderProfile.objects.select_for_update(of=("self",))
            .select_related("user")
            .get(pk=offer.provider_id)
        )

        # Create the rating for this completed job.
        ProviderRating.objects.create(
            job=job,
            provider=provider,
            customer=job.customer,
            rating=rating_value,
            comment=comment,
        )

        # Recalculate the provider's average rating.
        stats = ProviderRating.objects.filter(provider=provider).aggregate(
            average=Avg("rating"), count=Count("id")
        )

        # Update provider rating statistics.
        provider.average_rating = round(stats["average"] or 0, 2)
        provider.ratings_count = stats["count"]
        provider.completed_jobs = F("completed_jobs") + 1
        provider.save(
            update_fields=[
                "average_rating",
                "ratings_count",
                "completed_jobs",
                "updated_at",
            ]
        )
        # completed_jobs is now an F() expression in memory. Call
        # provider.refresh_from_db(fields=["completed_jobs"]) before reading it.

        # JobRequest.save() sets completed_at when the status becomes COMPLETED.
        job.status = JobRequestStatus.COMPLETED
        job.save(update_fields=["status", "completed_at", "updated_at"])

        pay_provider(job, offer)

        # Notify provider of completed job
        transaction.on_commit(
            lambda: create_job_completion_approved_notification(
                user=provider.user,
                job=job,
            )
        )

        # The rating comment text is intentionally not logged.
        logger.info(
            "Job completed and paid user_id=%s job_id=%s provider_id=%s rating=%s",
            request.user.pk,
            job.pk,
            provider.pk,
            rating_value,
        )

        return Response(
            {
                "detail": "Job completed successfully.",
                "rating": rating_value,
                "comment": comment,
                "provider_average_rating": float(provider.average_rating),
                "provider_ratings_count": provider.ratings_count,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Ratings"],
    summary="List ratings with comments left for me (provider)",
    description="Visible ratings that have a comment. Paginated.",
    responses={200: ProviderRatingSerializer, 401: UNAUTHORIZED, 403: NOT_ALLOWED},
)
class MyRatingsListView(generics.ListAPIView):
    """Comments left for the logged-in provider."""

    serializer_class = ProviderRatingSerializer
    permission_classes = [IsProvider]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ProviderRating.objects.none()
        return ProviderRating.objects.filter(
            provider=self.request.user.provider_profile, is_visible=True
        ).exclude(comment="")


@extend_schema(
    tags=["Ratings"],
    summary="List ratings with comments for a provider",
    description="Visible ratings that have a comment. Paginated.",
    parameters=[PROVIDER_ID],
    responses={200: ProviderRatingSerializer, 401: UNAUTHORIZED},
)
class ProviderRatingsPublicListView(generics.ListAPIView):
    """Comments left for a given provider, for customers browsing."""

    serializer_class = ProviderRatingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ProviderRating.objects.none()
        return ProviderRating.objects.filter(
            provider_id=self.kwargs["provider_id"], is_visible=True
        ).exclude(comment="")


@extend_schema(
    tags=["Disputes"],
    summary="Open a dispute on a job (job owner)",
    description=(
        "Only while the job is awaiting confirmation and before its deadline. "
        "Moves the job to disputed and notifies the provider and admins."
    ),
    parameters=[JOB_ID],
    request=JobDisputeSerializer,
    responses={
        201: JobDisputeSerializer,
        400: OpenApiResponse(
            description=((
                "Validation error, job not awaiting confirmation, deadline passed, "
                "or a dispute already exists."
            ) + STATE_ERROR_NOTE)
        ),
        401: UNAUTHORIZED,
        403: NOT_ALLOWED,
        404: JOB_NOT_FOUND,
        429: THROTTLED,
    },
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
        job = self.get_locked_job()

        self.check_job_owner(job)
        self.ensure_job_is_awaiting_confirmation(
            job, "Only the jobs awaiting confirmation can be disputed."
        )

        if job.deadline is not None and job.deadline <= timezone.now():
            return Response(
                {
                    "detail": "The deadline has passed. This job will be settled automatically."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        accepted_offer = get_object_or_404(
            JobRequestOffer.objects.select_related("provider__user"),
            job=job,
            status=JobOfferStatus.ACCEPTED,
        )

        # Check if a dispute already exists for this job.
        if JobDispute.objects.filter(job=job).exists():
            return Response(
                {"detail": "A dispute already exists for this job."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(job=job)

        # Mark the job as disputed.
        job.status = JobRequestStatus.DISPUTED
        job.save(update_fields=["status", "updated_at"])

        # Notify the provider after the transaction commits.
        provider_user = accepted_offer.provider.user
        transaction.on_commit(
            lambda: create_dispute_opened_notification(
                user=provider_user, job=job)
        )

        # Notify administrators after the transaction commits.
        admin_users = list(User.objects.filter(
            role=UserRole.ADMIN, is_active=True))
        for admin in admin_users:
            transaction.on_commit(
                lambda user=admin: create_dispute_opened_admin_notification(
                    user=user, job=job
                )
            )

        logger.info(
            "Dispute opened user_id=%s job_id=%s dispute_id=%s",
            request.user.pk,
            job.pk,
            serializer.instance.pk,
        )

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Disputes"],
    summary="Get a dispute (job owner or admin)",
    responses={
        200: JobDisputeSerializer,
        401: UNAUTHORIZED,
        403: NOT_ALLOWED,
        404: OpenApiResponse(description="Dispute not found."),
        429: THROTTLED,
    },
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
        return JobDispute.objects.select_for_update(of=("self", "job")).select_related(
            "job", "job__customer__user"
        )

    @extend_schema(
        tags=["Disputes"],
        summary="Resolve a dispute (admin)",
        description=(
            "`decision` is required: `refund_points` cancels the job and refunds the "
            "customer; `release_points` completes the job and pays the provider."
        ),
        request=AdminJobDisputeSerializer,
        responses={
            200: AdminJobDisputeSerializer,
            400: OpenApiResponse(
                description=((
                    "Validation error, missing/invalid decision, dispute already "
                    "resolved, or the job is not disputed."
                ) + STATE_ERROR_NOTE)
            ),
            401: UNAUTHORIZED,
            403: NOT_ALLOWED,
            404: OpenApiResponse(description="Dispute not found."),
            429: THROTTLED,
        },
    )
    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        dispute = self.get_object()
        self.ensure_dispute_is_unresolved(dispute)

        job = dispute.job
        if job.status != JobRequestStatus.DISPUTED:
            raise ValidationError(
                {"detail": "This job is not in a disputed state."})

        serializer = self.get_serializer(
            dispute, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        decision = serializer.validated_data.get("decision")
        if decision not in (
            JobDisputeDecision.REFUND_POINTS,
            JobDisputeDecision.RELEASE_POINTS,
        ):
            raise ValidationError(
                {"decision": "A valid decision is required."})

        offer = get_object_or_404(
            JobRequestOffer.objects.select_related("provider__user"),
            job=job,
            status=JobOfferStatus.ACCEPTED,
        )

        dispute = serializer.save(resolved_by=request.user)

        customer_user = job.customer.user
        provider_user = offer.provider.user

        if decision == JobDisputeDecision.REFUND_POINTS:
            job.status = JobRequestStatus.CANCELLED
            release_reserved_points(
                job, transaction_type=TransactionType.REFUND)

            transaction.on_commit(
                lambda: create_dispute_refunded_customer_notification(
                    user=customer_user, job=job
                )
            )
            transaction.on_commit(
                lambda: create_dispute_cancelled_provider_notification(
                    user=provider_user, job=job
                )
            )
        else:  # RELEASE_POINTS
            job.status = JobRequestStatus.COMPLETED
            job.completed_at = timezone.now()

            pay_provider(job, offer)

            offer.provider.completed_jobs = F("completed_jobs") + 1
            offer.provider.save(update_fields=["completed_jobs", "updated_at"])
            # Call offer.provider.refresh_from_db(fields=["completed_jobs"]) first,
            # if you need the value of completed_jobs immediately after saving.

            transaction.on_commit(
                lambda: create_dispute_released_customer_notification(
                    user=customer_user, job=job
                )
            )
            transaction.on_commit(
                lambda: create_dispute_released_provider_notification(
                    user=provider_user, job=job
                )
            )

        job.save(update_fields=["status", "completed_at", "updated_at"])

        logger.info(
            "Dispute resolved admin_id=%s dispute_id=%s job_id=%s decision=%s",
            request.user.pk,
            dispute.pk,
            job.pk,
            decision,
        )

        return Response(serializer.data, status=status.HTTP_200_OK)
