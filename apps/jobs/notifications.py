from apps.mails.services import create_mailbox_message

from apps.core.choices import UserRole


# job_created_notification: Creates a notification for a user when they create a job.
# It constructs a message with the job details and sends it to the user using the create_mailbox_message function.
def create_job_created_notification(user, job):
    job_details = [
        ("Job ID", job.id),
        ("Job Category", job.category.name),
        ("Job Title", job.title),
        ("Job Scheduled Points", job.points_amount),
        ("Job Deadline", job.deadline),
        ("Job Primary Location", job.primary_location),
    ]

    if job.secondary_location:
        job_details.append(("Job Secondary Location", job.secondary_location))

    text_details = "\n".join(f"{label}: {value}" for label, value in job_details)

    text_content = (
        f"Hi {user.first_name},\n\n"
        "You just created a job. Details are below:\n\n"
        f"{text_details}\n\n"
        "Hope your job gets done to your satisfaction.\n\n"
        "Thanks."
    )

    return create_mailbox_message(
        user=user, subject=f"{job.title} Job Created", body=text_content
    )


# job_updated_notification: Creates a notification for a user when their job is updated.
def create_job_updated_notification(user, job):
    return create_mailbox_message(
        user=user,
        subject=f"{job.title} Job Updated",
        body=(
            f"Hi {user.first_name},\n\n"
            f"Your job '{job.title}' has been updated successfully.\n\n"
            "Please check your account for more details.\n\n"
            "Thanks."
        ),
    )


# job_cancelled_notification: Creates a notification for a list of users when a job is cancelled.
# It iterates through the list of users and sends a message to each user with details about the cancelled job using the create_mailbox_message function.
def create_job_cancelled_notification(users, job):
    for user in users:
        create_mailbox_message(
            user=user,
            subject=f"{job.title} Job Cancelled",
            body=(
                f"Hi {user.first_name},\n\n"
                f"The job '{job.title}' has been cancelled.\n\n"
                "A job is cancelled when the owner cancels or the job reaches its deadline.\n\n"
                "Thanks."
            ),
        )


def create_job_cancelled_provider_partial_pay_notification(users, job):
    for user in users:
        create_mailbox_message(
            user=user,
            subject=f"{job.title} Job Cancelled",
            body=(
                f"Hi {user.first_name},\n\n"
                f"The job '{job.title}' has been cancelled.\n\n"
                "Since the job was in-progress, a 20% of the job points was paid to the provider.\n\n"
                "Thanks."
            ),
        )


# job_new_offer_notification: Creates a notification for a user when they receive a new offer for their job.
def create_job_new_offer_notification(user, job):
    return create_mailbox_message(
        user=user,
        subject=f"New Offer for {job.title}",
        body=(
            f"Hi {user.first_name},\n\n"
            f"You have received a new offer for your job '{job.title}'.\n\n"
            "Please check your account for more details.\n\n"
            "Thanks."
        ),
    )


def create_job_offer_accepted_notification(user, job):
    return create_mailbox_message(
        user=user,
        subject=f"Offer Accepted for {job.title}",
        body=(
            f"Hi {user.first_name},\n\n"
            f"Your offer for the job '{job.title}' has been accepted.\n\n"
            "Please check your account for more details.\n\n"
            "Thanks."
        ),
    )


def create_job_offer_rejected_notification(user, job):
    return create_mailbox_message(
        user=user,
        subject=f"Offer Rejected for {job.title}",
        body=(
            f"Hi {user.first_name},\n\n"
            f"Your offer for the job '{job.title}' has been rejected.\n\n"
            "Please check your account for more details.\n\n"
            "Thanks."
        ),
    )


def create_job_completion_request_notification(user, job):
    return create_mailbox_message(
        user=user,
        subject=f"Job Completion Requested for {job.title}",
        body=(
            f"Hi {user.first_name},\n\n"
            f"The provider has requested completion for the job '{job.title}'.\n\n"
            "Please check your account for more details.\n\n"
            "Thanks."
        ),
    )


def create_job_completion_approved_notification(user, job):
    return create_mailbox_message(
        user=user,
        subject=f"Job Completion Approved for {job.title}",
        body=(
            f"Hi {user.first_name},\n\n"
            f"The job '{job.title}' has been marked as completed.\n\n"
            f"Please note that 10% of the job points will be deducted as the administrative fee.\n\n"
            f"Administrative fee is {job.admin_fee_points}.\n\n"
            f"Your credited points is {job.provider_earning_points}.\n\n"
            "Please check your account for more details.\n\n"
            "Thanks."
        ),
    )


def create_job_completed_by_deadline_notification(users, job):
    provider_note = (
        f"Please note that 10% of the job points will be deducted as the administrative fee.\n\n"
        f"Administrative fee is {job.admin_fee_points}.\n\n"
        f"Your credited points is {job.provider_earning_points}.\n\n"
    )
    for user in users:
        create_mailbox_message(
            user=user,
            subject=f"{job.title} Completed",
            body=(
                f"Hi {user.first_name},\n\n"
                f"The job '{job.title}' has been marked as complete.\n\n"
                f"The provider has been paid in full.\n\n"
                "This is because, the job deadline has reached and the provider is done with the job, so the job was awaiting confirmation when the deadline reached.\n\n"
                f"{provider_note if user.role == UserRole.PROVIDER else ''}"
                "Please check your account for more details.\n\n"
                "Thanks."
            ),
        )


def create_dispute_opened_notification(user, job):
    return create_mailbox_message(
        user=user,
        subject=f"Dispute Opened for {job.title}",
        body=(
            f"Hi {user.first_name},\n\n"
            f"A dispute has been opened for the job '{job.title}'.\n\n"
            "Please check your account for more details.\n\n"
            "Thanks."
        ),
    )


def create_dispute_opened_admin_notification(user, job):
    return create_mailbox_message(
        user=user,
        subject=f"New Dispute: {job.title}",
        body=(
            f"Hi {user.first_name},\n\n"
            f"A customer has opened a dispute for the job '{job.title}'.\n\n"
            "Please review the dispute in the admin panel.\n\n"
            "Thanks."
        ),
    )


def create_dispute_refunded_customer_notification(user, job):
    return create_mailbox_message(
        user=user,
        subject=f"Dispute Resolved: {job.title}",
        body=(
            f"Hi {user.first_name},\n\n"
            f"Your dispute for the job '{job.title}' has been resolved "
            "in your favor. Your points have been refunded.\n\n"
            "Please check your account for more details.\n\n"
            "Thanks."
        ),
    )


def create_dispute_cancelled_provider_notification(user, job):
    return create_mailbox_message(
        user=user,
        subject=f"Job Cancelled: {job.title}",
        body=(
            f"Hi {user.first_name},\n\n"
            f"The dispute for the job '{job.title}' has been resolved. "
            "The job has been cancelled and the customer's points "
            "have been refunded.\n\n"
            "Please check your account for more details.\n\n"
            "Thanks."
        ),
    )


def create_dispute_released_customer_notification(user, job):
    return create_mailbox_message(
        user=user,
        subject=f"Dispute Resolved: {job.title}",
        body=(
            f"Hi {user.first_name},\n\n"
            f"The dispute for the job '{job.title}' has been resolved. "
            "The provider has been paid and the job has been marked "
            "as completed.\n\n"
            "Please check your account for more details.\n\n"
            "Thanks."
        ),
    )


def create_dispute_released_provider_notification(user, job):
    return create_mailbox_message(
        user=user,
        subject=f"Payment Released: {job.title}",
        body=(
            f"Hi {user.first_name},\n\n"
            f"The dispute for the job '{job.title}' has been resolved "
            "in your favor. Your payment has been released and the "
            "job has been marked as completed.\n\n"
            "Please check your account for more details.\n\n"
            "Thanks."
        ),
    )
