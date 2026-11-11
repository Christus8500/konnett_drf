import hashlib
import time

from django.core.cache import cache


def _version_key(user_id):
    return f"mailbox:ver:{user_id}"


def _get_version(user_id):
    version = cache.get(_version_key(user_id))
    if version is None:
        version = time.time_ns()
        cache.set(_version_key(user_id), version, None)
    return version


def messages_key(user_id, query_params):
    # Hash the page parameters so user input never goes into a key directly
    raw = f"{query_params.get('page', '1')}:{query_params.get('page_size', '')}"
    digest = hashlib.sha1(raw.encode()).hexdigest()[:16]
    return f"mailbox:messages:{user_id}:v{_get_version(user_id)}:{digest}"


def unread_count_key(user_id):
    return f"mailbox:unread-count:{user_id}"


def invalidate_mailbox(user_id):
    """Call after any change to a user's messages, including bulk updates."""
    cache.set(_version_key(user_id), time.time_ns(), None)
    cache.delete(unread_count_key(user_id))