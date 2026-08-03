from django.db import transaction
from django.db.models import F
from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import viewsets, generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser
from rest_framework.filters import OrderingFilter, SearchFilter

from apps.core.permissions import IsCustomer, IsCustomerOwner, IsVerifiedProvider
from apps.core.choices import JobRequestStatus, JobOfferStatus, JobDisputeDecision
from apps.jobs.models import JobRequest, JobRequestImage, JobRequestOffer, JobDispute
from apps.jobs.mixins import JobRequestMixin, ProviderMixin
from apps.jobs.serializers import JobRequestReadSerializer, JobRequestWriteSerializer, JobRequestImageSerializer, JobCompletionImageSerializer, JobRequestOfferSerializer, JobDisputeSerializer, AdminJobDisputeSerializer
from apps.jobs.filters import JobFilter

# Create your views here.


class JobRequestViewSet(JobRequestMixin, viewsets.ModelViewSet):
    http_method_names = ["post", "get", "patch", "delete"]
    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]
    filterset_class = JobFilter
    search_fields = ["title", "description"]
    ordering_fields = ["created_at", "points_amount"]

    #^ get_queryset retrieves the queryset of JobRequest instances based on the authenticated user's role.
    # If the user is a staff member, all job requests are returned.
    # If the user is a customer, only their own job requests are returned.
    # If the user is a provider, only pending job requests are returned.
    def get_queryset(self):
        queryset = (
            JobRequest.objects.select_related(
                "customer",
                "category",
            ).prefetch_related(
                "job_request_images",
                "job_completion_images",
                "job_offers__provider",
            )
        )

        user = self.request.user
        if user.is_staff:
            return queryset
        if hasattr(user, "customer_profile"):
            return queryset.filter(customer=user.customer_profile)
        if hasattr(user, "provider_profile"):
            return queryset.filter(status=JobRequestStatus.PENDING)
        return queryset.none()

    #^ get_serializer_class returns the appropriate serializer class based on the action being performed.
    def get_serializer_class(self):
        if self.action in ['create', 'partial_update']:
            return JobRequestWriteSerializer
        return JobRequestReadSerializer

    #^ get_permissions returns the appropriate permissions based on the action being performed
    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            permission = IsCustomer | IsVerifiedProvider | IsAdminUser
            return [permission()]
        elif self.action in ["partial_update", "destroy"]:
            return [IsCustomerOwner()]
        return [IsCustomer()]

    def perform_create(self, serializer):
        # TODO (Konnett Points):
        # Check if the customer has enough available points.
        #
        # TODO (Konnett Points):
        # Reserve (lock) the points for this job.
        serializer.save(customer=self.request.user.customer_profile)

    #^ partial_update updates a job request instance. 
    # It ensures that the job is still pending before allowing the update. 
    # If the job is not pending, an error message is returned.
    def partial_update(self, request, *args, **kwargs):
        job = self.get_object()
        self.ensure_job_is_pending(
            job,
            "This job can no longer be edited."
        )
        return super().partial_update(request, *args, **kwargs)

    #^ destroy cancels a job request instance.
    # It ensures that the job is still pending or open before allowing the cancellation. 
    # If the job is not in one of these states, an error message is returned.
    def destroy(self, request, *args, **kwargs):
        job = self.get_object()
        self.ensure_job_is_pending_or_open(job)

        job.status = JobRequestStatus.CANCELLED
        job.save(update_fields=["status"])

        # TODO (Konnett Points):
        # Release the reserved points back to the customer's
        # available balance.
        return Response(status=status.HTTP_204_NO_CONTENT)


class JobRequestImageCreateView(JobRequestMixin, generics.CreateAPIView):
    serializer_class = JobRequestImageSerializer
    permission_classes = [IsCustomer]

    def create(self, request, *args, **kwargs):
        job = self.get_job()

        self.check_job_owner(job)
        self.ensure_job_is_pending(job)

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


class JobRequestImageDeleteView(JobRequestMixin, generics.DestroyAPIView):
    permission_classes = [IsCustomer]
    queryset = JobRequestImage.objects.all()

    def destroy(self, request, *args, **kwargs):
        image = self.get_object()
        job = image.job

        self.check_job_owner(job)
        self.ensure_job_is_pending(job)

        image.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


class JobOfferView(JobRequestMixin, generics.ListCreateAPIView):
    serializer_class = JobRequestOfferSerializer

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
        # Provider endpoint: /provider/offers/
        if "pk" not in self.kwargs:
            return (
                JobRequestOffer.objects
                .filter(
                    provider=self.request.user.provider_profile,
                    job__status=JobRequestStatus.PENDING,
                )
                .select_related("provider", "job")
                .order_by("-created_at")
            )

        # Customer endpoint: /jobs/<job_id>/offers/
        job = self.get_job()
        self.check_job_owner(job)

        return (
            JobRequestOffer.objects
            .filter(job=job)
            .select_related("provider", "job")
            .order_by("-created_at")
        )
    
    def create(self, request, *args, **kwargs):
        if "pk" not in self.kwargs:
            return Response(
                {"detail": "Offers can only be created for a specific job."},
                status=status.HTTP_405_METHOD_NOT_ALLOWED,
            )

        job = self.get_job()
        self.ensure_job_is_pending_or_open(
            job,
            "This job is no longer accepting offers."
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

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


class JobOfferAcceptView(JobRequestMixin, ProviderMixin, generics.UpdateAPIView):
    queryset = JobRequestOffer.objects.select_related("job")
    permission_classes = [IsCustomer]

    # transaction.atomic ensures that the entire operation is treated as a single transaction. 
    # If any part of the operation fails, the entire transaction will be rolled back, ensuring data integrity.
    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        offer = self.get_object()
        job = offer.job

        self.check_job_owner(job)
        self.ensure_job_is_open(
            job,
            "Offers can only be managed while the job is open"
        )

        self.ensure_offer_is_pending(
            offer,
            "This offer has already been processed."
        )

        offer.status = JobOfferStatus.ACCEPTED
        offer.save(update_fields=["status"])

        JobRequestOffer.objects.filter(
            job=job,
            status=JobOfferStatus.PENDING,
        ).exclude(
            pk=offer.pk
        ).update(
            status=JobOfferStatus.REJECTED
        )

        job.status = JobRequestStatus.IN_PROGRESS
        job.save(update_fields=["status"])

        # TODO:
        # Notify the accepted provider.

        # TODO:
        # Notify all rejected providers.

        return Response(
            {"detail": "Offer accepted."},
            status=status.HTTP_200_OK
        )


class JobOfferRejectView(JobRequestMixin, ProviderMixin, generics.UpdateAPIView):
    queryset = JobRequestOffer.objects.select_related("job")
    permission_classes = [IsCustomer]
    
    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        offer = self.get_object()
        job = offer.job

        self.check_job_owner(job)
        self.ensure_job_is_open(
            job,
            "You can only reject offers while the job is open.",
        )

        self.ensure_offer_is_pending(
            offer,
            "This offer has already been processed."
        )

        offer.status = JobOfferStatus.REJECTED
        offer.save(update_fields=["status"])

        return Response(
            {"detail": "Offer rejected."},
            status=status.HTTP_200_OK,
        )


class JobOfferWithdrawView(ProviderMixin, JobRequestMixin, generics.UpdateAPIView):
    queryset = JobRequestOffer.objects.select_related(
        "job",
        "provider",
    )
    permission_classes = [IsVerifiedProvider]

    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        offer = self.get_object()
        job = offer.job

        self.check_offer_owner(offer)
        self.ensure_job_is_open(
            job,
            "You can only withdraw offers from open jobs."
        )

        self.ensure_offer_is_pending(
            offer,
            "Only pending offers can be withdrawn."
        )

        offer.status = JobOfferStatus.WITHDRAWN
        offer.save(update_fields=["status"])

        return Response(
            {"detail": "Offer withdrawn."},
            status=status.HTTP_200_OK,
        )


class JobCompletionImageCreateView(JobRequestMixin, ProviderMixin, generics.CreateAPIView):
    serializer_class = JobCompletionImageSerializer
    permission_classes = [IsVerifiedProvider]

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        job = self.get_job()

        self.ensure_job_is_in_progress(
            job,
            "Completion images can only be uploaded while the job is in progress."
        )

        offer = self.check_accepted_provider(job)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        serializer.save(
            job=job,
            provider=offer.provider,
        )

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


class JobRequestCompletionView(JobRequestMixin, ProviderMixin, generics.UpdateAPIView):
    permission_classes = [IsVerifiedProvider]

    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        job = self.get_job()

        self.ensure_job_is_in_progress(
            job,
            "Only the jobs in progress can request completion"
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

        return Response(
            {
                "detail": (
                    "Completion request sent successfully."
                )
            },
            status=status.HTTP_200_OK,
        )


class JobConfirmCompletionView(JobRequestMixin, generics.UpdateAPIView):
    permission_classes = [IsCustomer]

    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        job = self.get_job()

        self.check_job_owner(job)
        self.ensure_job_is_awaiting_confirmation(
            job,
            "Only the jobs awaiting completion can be completed"
        )

        offer = JobRequestOffer.objects.select_related(
            "provider"
        ).get(
            job=job,
            status=JobOfferStatus.ACCEPTED,
        )

        job.status = JobRequestStatus.COMPLETED
        job.save(update_fields=["status"])

        # TODO (Konnett Points):
        # Transfer the reserved points from the customer's
        # PointAccount to the accepted provider's PointAccount.

        # TODO (Konnett Points):
        # Create a PointTransaction record for both
        # customer and provider.

        offer.provider.completed_jobs = F("completed_jobs") + 1
        offer.provider.save(update_fields=["completed_jobs"])
        offer.provider.refresh_from_db()

        return Response(
            {"detail": "Job completed successfully."},
            status=status.HTTP_200_OK,
        )


class JobDisputeCreateView(JobRequestMixin, generics.CreateAPIView):
    serializer_class = JobDisputeSerializer
    permission_classes = [IsCustomer]

    # create handles the creation of a new dispute for a specific job.
    # It ensures that the job is still awaiting confirmation before allowing the creation of a dispute.
    def create(self, request, *args, **kwargs):
        job = self.get_job()
        self.check_job_owner(job)

        self.ensure_job_is_awaiting_confirmation(
            job,
            "Only the jobs awaiting confirmation can be disputed."
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

        job.status = JobRequestStatus.DISPUTED
        job.save(update_fields=["status"])

        # TODO:
        # Notify administrators that a dispute
        # has been opened.

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


class JobDisputeDetailView(JobRequestMixin, generics.RetrieveAPIView):
    serializer_class = JobDisputeSerializer
    permission_classes = [IsCustomer | IsAdminUser]
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
    queryset = JobDispute.objects.select_related(
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

        if dispute.decision == JobDisputeDecision.REFUND_POINTS:
            job.status = JobRequestStatus.CANCELLED

            # TODO (Konnett Points):
            # Refund the reserved points
            # back to the customer.

            # TODO (Konnett Points):
            # Create PointTransaction records.

            # TODO:
            # Notify customer and provider.

        elif dispute.decision == JobDisputeDecision.RELEASE_POINTS:
            job.status = JobRequestStatus.COMPLETED

            # TODO (Konnett Points):
            # Transfer the reserved points
            # to the provider.

            # TODO (Konnett Points):
            # Create PointTransaction records.

            # TODO:
            # Notify customer and provider.

        job.save(update_fields=["status"])

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )
