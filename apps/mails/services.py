from apps.mails.models import MailboxMessage


def create_mailbox_message(user, subject, body):
    return MailboxMessage.objects.create(
        user=user,
        subject=subject,
        body=body,
    )