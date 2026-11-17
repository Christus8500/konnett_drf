import logging

from django.conf import settings
from django.utils import timezone

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.pagination import PageNumberPagination

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view

from apps.core.utils import THROTTLED, UNAUTHORIZED, get_cache, set_cache

from apps.mails.models import MailboxMessage
from apps.mails.serializers import (
    MailboxMessageListSerializer,
    MailboxMessageSerializer,
    MailboxUnreadCountSerializer,
)
from apps.mails.cache_keys import messages_key, unread_count_key

logger = logging.getLogger(__name__)

MESSAGE_NOT_FOUND = OpenApiResponse(description="Message not found.")

# Create your views here.

class MailboxPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


@extend_schema_view(
    list=extend_schema(
        tags=["Mailbox"],
        summary="List my messages",
        description="Paginated, newest first. Cached per page.",
        responses={
            200: MailboxMessageListSerializer,  # spectacular adds the pagination wrapper
            401: UNAUTHORIZED,
            404: OpenApiResponse(description="Invalid page."),
            429: THROTTLED,
        },
    ),
    retrieve=extend_schema(
        tags=["Mailbox"],
        summary="Get a message",
        responses={
            200: MailboxMessageSerializer,
            401: UNAUTHORIZED,
            404: MESSAGE_NOT_FOUND,
            429: THROTTLED,
        },
    ),
    destroy=extend_schema(
        tags=["Mailbox"],
        summary="Delete a message",
        responses={
            204: OpenApiResponse(description="Message deleted."),
            401: UNAUTHORIZED,
            404: MESSAGE_NOT_FOUND,
            429: THROTTLED,
        },
    ),
)
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
        if getattr(self, "swagger_fake_view", False):
            return MailboxMessage.objects.none()
        return MailboxMessage.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action == "list":
            return MailboxMessageListSerializer

        return MailboxMessageSerializer

    def list(self, request, *args, **kwargs):
        key = messages_key(request.user.id, request.query_params, self.paginator)
        data = get_cache(key)

        if data is None:
            queryset = self.filter_queryset(self.get_queryset())
            page = self.paginate_queryset(queryset)  # raises 404 for an invalid page
            serializer = self.get_serializer(page, many=True)
            data = self.get_paginated_response(serializer.data).data
            set_cache(key, data, timeout=settings.BIG_CACHE_TIMEOUT)
        else:
            logger.debug("Mailbox list served from cache user_id=%s", request.user.id)

        return Response(data)

    def perform_destroy(self, instance):
        message_id = instance.pk
        super().perform_destroy(instance)
        logger.info(
            "Mailbox message deleted user_id=%s message_id=%s",
            self.request.user.pk,
            message_id,
        )

    @extend_schema(
        tags=["Mailbox"],
        summary="Count my unread messages",
        description="Cached.",
        responses={
            200: MailboxUnreadCountSerializer,
            401: UNAUTHORIZED,
            429: THROTTLED,
        },
    )
    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        key = unread_count_key(request.user.id)
        count = get_cache(key)
        if count is None:
            count = self.get_queryset().filter(is_read=False).count()
            set_cache(key, count, timeout=settings.BIG_CACHE_TIMEOUT)
        return Response({"count": count})

    @extend_schema(
        tags=["Mailbox"],
        summary="Mark a message as read",
        description="No request body. Safe to call again on an already-read message.",
        request=None,
        responses={
            200: MailboxMessageSerializer,
            401: UNAUTHORIZED,
            404: MESSAGE_NOT_FOUND,
            429: THROTTLED,
        },
    )
    @action(detail=True, methods=["patch"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        message = self.get_object()
        message.mark_as_read()
        logger.debug(
            "Mailbox message marked read user_id=%s message_id=%s",
            request.user.pk,
            message.pk,
        )
        return Response(MailboxMessageSerializer(message).data)
