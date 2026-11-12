"""سریالایزرهای مشاهده و راستی‌آزمایی زنجیرهٔ حسابرسی."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.core.jalali import format_jalali_datetime


class AuditRecordSerializer(serializers.Serializer[Any]):
    """نمای خروجی یک رکورد حسابرسی."""

    id = serializers.UUIDField()
    sequence = serializers.IntegerField()
    action = serializers.CharField()
    outcome = serializers.CharField()
    actor_id = serializers.UUIDField(allow_null=True)
    actor_label = serializers.CharField()
    target_type = serializers.CharField()
    target_id = serializers.CharField()
    reason = serializers.CharField()
    metadata = serializers.JSONField()
    request_id = serializers.CharField()
    previous_hash = serializers.CharField()
    record_hash = serializers.CharField()
    created_at = serializers.DateTimeField()
    created_at_jalali = serializers.SerializerMethodField()

    def get_created_at_jalali(self, obj: Any) -> str | None:
        """معادل تاریخ و ساعت شمسی ثبت رکورد."""
        return format_jalali_datetime(obj.created_at)


class AuditChainVerificationSerializer(serializers.Serializer[dict[str, Any]]):
    """پاسخ راستی‌آزمایی زنجیرهٔ هش و لنگرها."""

    chain_valid = serializers.BooleanField()
    first_broken_sequence = serializers.IntegerField(allow_null=True)
    anchors_valid = serializers.BooleanField()
    broken_anchors = serializers.ListField(child=serializers.IntegerField())
    total_records = serializers.IntegerField()
