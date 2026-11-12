"""سریالایزرهای پارامتر و تاریخچهٔ خروجی‌های اکسل مدیریتی."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers


class ExcelExportQuerySerializer(serializers.Serializer[Any]):
    """پارامترهای فیلتر خروجی اکسل مدیریتی."""

    date_from = serializers.DateTimeField(required=False)
    date_to = serializers.DateTimeField(required=False)
    benefactor_id = serializers.UUIDField(required=False)
    campaign_id = serializers.UUIDField(required=False)
    include_raw_phones = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(max_length=400, required=False, allow_blank=True, default="")


class ReportExportLogSerializer(serializers.Serializer[Any]):
    """نمای تاریخچهٔ خروجی‌های اکسل صادرشده."""

    id = serializers.UUIDField()
    exported_by_id = serializers.UUIDField()
    filters = serializers.JSONField()
    include_raw_phones = serializers.BooleanField()
    reason = serializers.CharField()
    file_sha256 = serializers.CharField()
    byte_size = serializers.IntegerField()
    row_counts = serializers.JSONField()
    created_at = serializers.DateTimeField()
