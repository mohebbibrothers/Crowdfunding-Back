"""سریالایزرهای متادیتای قرارداد API، سلامت سرویس و مدیریت سیاست‌های پویا (Policy-as-Data)."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers


class ProblemDetailSerializer(serializers.Serializer[dict[str, Any]]):
    """اسکیمای استاندارد خطای RFC 9457 برای مستندسازی در OpenAPI 3.1."""

    type = serializers.URLField()
    title = serializers.CharField()
    status = serializers.IntegerField()
    detail = serializers.CharField()
    code = serializers.CharField()
    trace_id = serializers.CharField()

    def get_fields(self) -> dict[str, serializers.Field[Any, Any, Any, Any]]:
        fields = super().get_fields()
        fields["instance"] = serializers.CharField()
        fields["errors"] = serializers.DictField(
            child=serializers.ListField(child=serializers.CharField()),
            required=False,
        )
        return fields


class PlatformMetaSerializer(serializers.Serializer[dict[str, Any]]):
    """پاسخ نقطهٔ پایانی ``GET /api/v1/meta`` برای بوت‌استرپ فرانت‌اند."""

    service = serializers.CharField()
    environment = serializers.CharField()
    api_version = serializers.CharField()
    app_version = serializers.CharField()
    supported_versions = serializers.ListField(child=serializers.CharField())
    currency_base = serializers.CharField()
    currency_display_units = serializers.ListField(child=serializers.CharField())
    timezone = serializers.CharField()
    today_jalali = serializers.CharField()
    features = serializers.DictField(child=serializers.BooleanField())
    share_hold_ttl_minutes = serializers.IntegerField()


class HealthStatusSerializer(serializers.Serializer[dict[str, Any]]):
    """پاسخ بررسی سلامت سامانه."""

    status = serializers.CharField()
    checks = serializers.DictField(required=False)


class PolicyRuleOutputSerializer(serializers.Serializer[dict[str, Any]]):
    """نمای خروجی یک قانون سیاست سامانه برای پنل مدیریت."""

    key = serializers.CharField()
    value_type = serializers.CharField()
    value = serializers.JSONField()
    default = serializers.JSONField()
    description = serializers.CharField()
    version = serializers.IntegerField()


class PolicyUpdateInputSerializer(serializers.Serializer[dict[str, Any]]):
    """ورودی تغییر مقدار یک سیاست همراه با دلیل اجباری ممیزی."""

    value = serializers.JSONField()
    reason = serializers.CharField(min_length=5, max_length=400)
