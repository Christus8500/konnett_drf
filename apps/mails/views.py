from django.conf import settings
from django.utils import timezone

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.pagination import PageNumberPagination

from apps.core.utils import get_cache, set_cache

from apps.mails.models import MailboxMessage
from apps.mails.serializers import (
    MailboxMessageListSerializer,
    MailboxMessageSerializer,
)
from apps.mails.cache_keys import messages_key, unread_count_key

# Create your views here.

class MailboxPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class MailboxMessageViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):

    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]
    pagination_class = MailboxPagination

    def get_queryset(self):
        return MailboxMessage.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action == "list":
            return MailboxMessageListSerializer

        return MailboxMessageSerializer

    def list(self, request, *args, **kwargs):
        key = messages_key(request.user.id, request.query_params)
        data = get_cache(key)

        if data is None:
            queryset = self.filter_queryset(self.get_queryset())
            page = self.paginate_queryset(queryset)  # raises 404 for an invalid page
            serializer = self.get_serializer(page, many=True)
            data = self.get_paginated_response(serializer.data).data
            set_cache(key, data, timeout=settings.BIG_CACHE_TIMEOUT)

        return Response(data)

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        key = unread_count_key(request.user.id)
        count = get_cache(key)
        if count is None:
            count = self.get_queryset().filter(is_read=False).count()
            set_cache(key, count, timeout=settings.BIG_CACHE_TIMEOUT)
        return Response({"count": count})

    @action(detail=True, methods=["patch"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        message = self.get_object()
        message.mark_as_read()
        return Response(MailboxMessageSerializer(message).data)
