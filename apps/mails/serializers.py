from rest_framework import serializers

from apps.mails.models import MailboxMessage


class MailboxMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = MailboxMessage
        fields = [
            "id",
            "subject",
            "body",
            "is_read",
            "read_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "is_read",
            "read_at",
            "created_at",
        ]


class MailboxMessageListSerializer(serializers.ModelSerializer):
    class Meta:
        model = MailboxMessage
        fields = [
            "id",
            "subject",
            "is_read",
            "created_at",
        ]
