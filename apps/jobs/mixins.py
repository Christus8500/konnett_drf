from django.shortcuts import get_object_or_404

from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.jobs.models import JobRequest, JobRequestOffer
from apps.core.choices import JobRequestStatus, JobOfferStatus


class JobRequestMixin:
    """
    Helper methods for views that operate on a JobRequest.
    """

    # This method retrieves a JobRequest instance based on the primary key provided in the URL parameters.
    def get_job(self):
        return get_object_or_404(
            JobRequest,
            pk=self.kwargs["pk"]
        )

    def check_job_owner(self, job):
        """
        Ensure the authenticated customer owns the job.
        """
        if job.customer.user != self.request.user:
            raise PermissionDenied(
                "You do not own this job."
            )


    #^ These methods ensure that the job is in a specific status before allowing certain actions to be performed on it. 
    #^ If the job is not in the expected status, a ValidationError is raised with a custom message.

    def ensure_job_is_pending(self, job, message="This job is not pending."):
        if job.status != JobRequestStatus.PENDING:
            raise ValidationError(message)

    def ensure_job_is_open(self, job, message="This job is not open."):
        if job.status != JobRequestStatus.OPEN:
            raise ValidationError(message)

    def ensure_job_is_pending_or_open(self, job, message="Only pending or open jobs can be modified."):
        if job.status not in [JobRequestStatus.PENDING, JobRequestStatus.OPEN]:
            raise ValidationError(message)

    def ensure_job_is_in_progress(self, job, message="This job is not in progress."):
        if job.status != JobRequestStatus.IN_PROGRESS:
            raise ValidationError(message)

    def ensure_job_is_awaiting_confirmation(self, job, message="This job is not awaiting confirmation."):
        if job.status != JobRequestStatus.AWAITING_CONFIRMATION:
            raise ValidationError(message)

    def check_dispute_owner(self, dispute):
        if dispute.job.customer.user != self.request.user:
            raise PermissionDenied(
                "You do not own this dispute."
            )

    def ensure_dispute_is_unresolved(self, dispute):
        if dispute.decision:
            raise ValidationError("This dispute has been already resolved.")


class ProviderMixin:
    """
    Helper methods for views that operate on a JobRequestOffer.
    """

    def check_offer_owner(self, offer):
        if offer.provider.user != self.request.user:
            raise PermissionDenied(
                "You do not own this offer."
            )

    #^ check_accepted_provider checks if the authenticated provider is the accepted provider for a given job.
    # It retrieves the accepted JobRequestOffer for the job and compares the provider's user with the authenticated user. 
    # If they do not match, a PermissionDenied exception is raised.
    def check_accepted_provider(self, job):
        offer = get_object_or_404(
            JobRequestOffer.objects.select_related("provider"),
            job=job,
            status=JobOfferStatus.ACCEPTED,
        )

        if offer.provider.user != self.request.user:
            raise PermissionDenied(
                "You are not the accepted provider for this job."
            )

        return offer

    def ensure_offer_is_pending(self, offer, message="This offer is not pending."):
        if offer.status != JobOfferStatus.PENDING:
            raise ValidationError(message)
