"""
Mailbox cache keys use a per-user version stamp. Invalidation only bumps the
stamp, so every cached page and the unread count move to fresh keys at once and
the old entries simply expire. A request that read the DB just before a change
can only write to the old (now unused) version, so it can't leave stale data
behind.
"""

import hashlib
import time

from django.core.cache import cache


def _version_key(user_id):
    return f"mailbox:ver:{user_id}"


def _get_version(user_id):
    key = _version_key(user_id)
    version = cache.get(key)
    if version is None:
        # add() is atomic: if two requests race here, the first writer wins and
        # both then read the same value. Timeout None = never expires. If the
        # counter is ever evicted, a new time-based value can never repeat an old one.
        cache.add(key, time.time_ns(), None)
        version = cache.get(key)
        if version is None:  # evicted between add and get (very unlikely)
            version = time.time_ns()
    return version


def messages_key(user_id, query_params, paginator):
    """
    Key for one page of a user's messages. Only page/page_size are used, and
    page_size is normalised the way DRF does, so junk or out-of-range values
    can't create extra cache entries.
    """
    try:
        page_size = int(query_params.get(paginator.page_size_query_param, ""))
        if page_size < 1:
            raise ValueError
    except ValueError:
        page_size = paginator.page_size  # DRF's fallback for bad values
    page_size = min(page_size, paginator.max_page_size)

    page = query_params.get("page", "1")
    try:
        page = str(int(page))  # "01" and "1" share one entry
    except ValueError:
        pass  # e.g. "last"; an invalid page 404s and is never cached

    raw = f"{page}:{page_size}"
    digest = hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()[:16]
    return f"mailbox:messages:{user_id}:v{_get_version(user_id)}:{digest}"


def unread_count_key(user_id):
    return f"mailbox:unread-count:{user_id}:v{_get_version(user_id)}"


def invalidate_mailbox(user_id):
    """Call after any change to a user's messages, including bulk updates."""
    cache.set(_version_key(user_id), time.time_ns(), None)