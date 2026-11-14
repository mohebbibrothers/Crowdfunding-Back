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


class FinancialAlertSerializer(serializers.Serializer[dict[str, Any]]):
    """یک هشدار عملیاتی حلقهٔ پول (شدت، کد ماشین‌خوان و پیام فارسی)."""

    severity = serializers.ChoiceField(choices=["critical", "warning", "info"])
    code = serializers.CharField()
    message = serializers.CharField()


class MoneyLoopStatsSerializer(serializers.Serializer[dict[str, Any]]):
    """آمار اصلی حلقهٔ وجه: پرداخت‌های رهاشده، تعهدهای بازپرداخت و بدهی ریالی."""

    abandoned_payments = serializers.IntegerField()
    abandoned_amount_rial = serializers.IntegerField()
    stale_abandoned_over_1h = serializers.IntegerField()
    unresolved_late_captures = serializers.IntegerField()
    awaiting_refund_contributions = serializers.IntegerField()
    awaiting_refund_amount_rial = serializers.IntegerField()
    pending_refund_obligations = serializers.IntegerField()
    refund_liability_rial = serializers.IntegerField()
    manual_refunds_due = serializers.IntegerField()
    manual_refund_amount_rial = serializers.IntegerField()
    orphan_refund_obligations = serializers.IntegerField()


class OpsStatsSerializer(serializers.Serializer[dict[str, Any]]):
    """شمارنده‌های عملیاتی مرتبط (صندوق خروجی متوقف‌شده)."""

    dead_outbox_messages = serializers.IntegerField()


class FinancialHealthSerializer(serializers.Serializer[dict[str, Any]]):
    """گزارش کامل سلامت حلقهٔ وجه برای پنل عملیات."""

    status = serializers.CharField()
    generated_at = serializers.DateTimeField()
    money_loop = MoneyLoopStatsSerializer()
    recovery_ledger = serializers.DictField(child=serializers.IntegerField())
    refund_ledger = serializers.DictField(child=serializers.IntegerField())
    ops = OpsStatsSerializer()
    alerts = FinancialAlertSerializer(many=True)


class LateCaptureReconcileInputSerializer(serializers.Serializer[dict[str, Any]]):
    """ورودی اجرای دستی داوری پرداخت‌های رهاشده از پنل مدیریت."""

    batch_size = serializers.IntegerField(min_value=1, max_value=1000, required=False, default=100)
    dry_run = serializers.BooleanField(required=False, default=False)


class LateCaptureReconcileResultSerializer(serializers.Serializer[dict[str, Any]]):
    """خروجی آماری اجرای داوری پرداخت‌های رهاشده."""

    scanned = serializers.IntegerField()
    not_captured = serializers.IntegerField()
    recovered = serializers.IntegerField()
    refund_pending = serializers.IntegerField()
    manual_review = serializers.IntegerField()
    error_count = serializers.IntegerField()
    dry_run = serializers.BooleanField()
    candidate_ids = serializers.ListField(child=serializers.CharField(), required=False)


class RefundDispatchResultSerializer(serializers.Serializer[dict[str, Any]]):
    """خروجی آماری ارسال تعهدهای بازپرداخت به درگاه."""

    attempted = serializers.IntegerField()
    sent = serializers.IntegerField()
    manual = serializers.IntegerField()
    failed = serializers.IntegerField()
    skipped = serializers.IntegerField()
    over_cap = serializers.IntegerField(
        help_text="تعداد تعهدهایی که به‌دلیل عبور از سقف بازپرداخت خودکار به تأیید انسانی رفت."
    )


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
