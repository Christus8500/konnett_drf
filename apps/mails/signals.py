from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.mails.cache_keys import invalidate_mailbox
from apps.mails.models import MailboxMessage


@receiver(post_save, sender=MailboxMessage)
@receiver(post_delete, sender=MailboxMessage)
def mailbox_message_changed(sender, instance, **kwargs):
    user_id = instance.user_id
    transaction.on_commit(lambda: invalidate_mailbox(user_id))
