from django.conf import settings
from django.utils import timezone

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from apps.core.utils import get_cache, set_cache

from apps.mails.models import MailboxMessage
from apps.mails.serializers import (
    MailboxMessageListSerializer,
    MailboxMessageSerializer,
)

# Create your views here.


class MailboxMessageViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):

    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def get_queryset(self):
        return MailboxMessage.objects.filter(user=self.request.user)

    def get_serializer_class(self):

        if self.action == "list":
            return MailboxMessageListSerializer

        return MailboxMessageSerializer

    def list(self, request, *args, **kwargs):
        user_id = request.user.id
        cache_key = f"mailbox:messages:{user_id}"

        cached_data = get_cache(cache_key)

        if cached_data is not None:
            return Response(cached_data)

        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        set_cache(
            cache_key,
            serializer.data,
            timeout=settings.BIG_CACHE_TIMEOUT,
        )

        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        user_id = request.user.id
        message_id = kwargs["pk"]

        cache_key = f"mailbox:message:{user_id}:{message_id}"

        cached_data = get_cache(cache_key)

        if cached_data is not None:
            return Response(cached_data)

        instance = self.get_object()
        serializer = self.get_serializer(instance)

        set_cache(
            cache_key,
            serializer.data,
            timeout=settings.BIG_CACHE_TIMEOUT,
        )

        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        user_id = request.user.id
        cache_key = f"mailbox:unread-count:{user_id}"

        cached_data = get_cache(cache_key)

        if cached_data is not None:
            return Response({"count": cached_data})

        count = self.get_queryset().filter(is_read=False).count()

        set_cache(
            cache_key,
            count,
            timeout=settings.BIG_CACHE_TIMEOUT,
        )

        return Response({"count": count})

    @action(detail=True, methods=["patch"])
    def mark_read(self, request, pk=None):

        message = self.get_object()

        if not message.is_read:

            message.is_read = True
            message.read_at = timezone.now()

            message.save(update_fields=["is_read", "read_at"])

        return Response(
            MailboxMessageSerializer(message).data,
            status=status.HTTP_200_OK,
        )
