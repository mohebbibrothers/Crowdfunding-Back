"""سریالایزرهای اعلان‌های درون‌برنامه‌ای کاربر."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.core.jalali import format_jalali_datetime
from apps.notifications.models import UserNotification


class UserNotificationSerializer(serializers.Serializer[Any]):
    """نمای خروجی یک اعلان کاربر."""

    id = serializers.UUIDField()
    kind = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField()
    action_url = serializers.CharField()
    metadata = serializers.JSONField()
    is_read = serializers.SerializerMethodField()
    read_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    created_at_jalali = serializers.SerializerMethodField()

    def get_is_read(self, obj: UserNotification) -> bool:
        """آیا اعلان خوانده شده است؟"""
        return obj.read_at is not None

    def get_created_at_jalali(self, obj: UserNotification) -> str | None:
        """تاریخ شمسی ثبت اعلان."""
        return format_jalali_datetime(obj.created_at)


class MarkAllReadResponseSerializer(serializers.Serializer[Any]):
    """نمای پاسخ علامت‌گذاری همگانی اعلان‌ها."""

    marked_count = serializers.IntegerField()
