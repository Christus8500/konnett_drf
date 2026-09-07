from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.mails.models import MailboxMessage


@receiver(post_save, sender=MailboxMessage)
def mailbox_message_saved(sender, instance, **kwargs):
    user_id = instance.user_id

    cache.delete(f"mailbox:messages:{user_id}")
    cache.delete(f"mailbox:unread-count:{user_id}")
    cache.delete(f"mailbox:message:{user_id}:{instance.id}")


@receiver(post_delete, sender=MailboxMessage)
def mailbox_message_deleted(sender, instance, **kwargs):
    user_id = instance.user_id

    cache.delete(f"mailbox:messages:{user_id}")
    cache.delete(f"mailbox:unread-count:{user_id}")
    cache.delete(f"mailbox:message:{user_id}:{instance.id}")
