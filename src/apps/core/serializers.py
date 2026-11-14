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
    """پاسخ بررسی سلامت سامانه.

    ``status`` به‌جای رشتهٔ آزاد، مجموعهٔ بستهٔ سه‌حالته است: پایش‌گر
    (Kubernetes probe، لودبالانسر، داشبورد) باید بتواند روی مقدار مقایسه
    کند؛ رشتهٔ آزاد یعنی «شاید فردا چیز دیگری باشد».
    """

    status = serializers.ChoiceField(choices=["healthy", "degraded", "unhealthy"])
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


class MoneyTruthPanelSerializer(serializers.Serializer[dict[str, Any]]):
    """پنل «حقیقت وجه» — تنها عددی که می‌توان به هیئت‌مدیره گفت."""

    verified_but_unconfirmed = serializers.IntegerField(
        help_text="پرداخت‌هایی که ما تأیید کردیم ولی صورتحساب مستقل هنوز تأییدشان نکرده."
    )
    statement_confirmed = serializers.IntegerField(
        help_text="تنها پرداخت‌هایی که یک منبع مستقل تأییدشان کرده است."
    )
    statement_missing = serializers.IntegerField(
        help_text="پرداخت‌های تأییدشدهٔ ما که در صورتحساب درگاه وجود ندارند."
    )
    conflict = serializers.IntegerField(
        help_text="تناقض قطعی بین دفتر ما و صورتحساب — باید همیشه صفر باشد."
    )
    last_statement_at = serializers.DateTimeField(allow_null=True)
    statement_age_hours = serializers.FloatField(
        allow_null=True, help_text="کهنگی آخرین سند ورودی."
    )
    unresolved_findings = serializers.IntegerField(
        help_text="ردیف‌های مغایرتی که هنوز بررسی انسانی نشده‌اند."
    )
    unresolved_impact_rial = serializers.IntegerField(help_text="اثر ریالی خالص مغایرت‌های حل‌نشده.")
    statements_total = serializers.IntegerField()
    rows_pending_verdict = serializers.IntegerField(
        help_text="ردیف‌هایی که تطبیق ندیده‌اند — باید صفر باشند."
    )


class ReconcileInputSerializer(serializers.Serializer[dict[str, Any]]):
    """بدنهٔ اجرای تطبیق/اقدام روی یک صورت‌حساب.

    پیش‌فرض ``dry_run=True`` عمدی است: این عملیات وضعیت حقیقت صدها پرداخت را
    تغییر می‌دهد و پیش‌فرض باید بی‌خطر باشد. اپراتور باید صریحاً بگوید «اجرا کن».
    """

    dry_run = serializers.BooleanField(
        default=True,
        help_text="در حالت پیش‌فرض هیچ نوشتنی انجام نمی‌شود؛ برای اجرای واقعی false بفرستید.",
    )


class FinancialHealthSerializer(serializers.Serializer[dict[str, Any]]):
    """گزارش کامل سلامت حلقهٔ وجه برای پنل عملیات."""

    status = serializers.ChoiceField(choices=["healthy", "attention_required"])
    generated_at = serializers.DateTimeField()
    money_loop = MoneyLoopStatsSerializer()
    recovery_ledger = serializers.DictField(child=serializers.IntegerField())
    refund_ledger = serializers.DictField(child=serializers.IntegerField())
    ops = OpsStatsSerializer()
    alerts = FinancialAlertSerializer(many=True)
    money_truth = MoneyTruthPanelSerializer(
        required=False,
        help_text="لایهٔ حقیقت وجه: فاصلهٔ «تأیید خودگواه» و «تأیید مستقل صورت‌حساب».",
    )


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


# ══════════════════════════════════════════════════════════════════════════════
# لایهٔ حقیقت وجه — صورت‌حساب تسویهٔ درگاه
# ══════════════════════════════════════════════════════════════════════════════


class SettlementRowInputSerializer(serializers.Serializer[dict[str, Any]]):
    """یک ردیف ورودی صورت‌حساب (ورود از API به‌جای فایل)."""

    authority = serializers.CharField(
        max_length=80, help_text="شناسهٔ Authority تراکنش در درگاه (اجباری)."
    )
    amount_rial = serializers.CharField(
        max_length=40,
        required=False,
        allow_blank=True,
        help_text="مبلغ ریالی؛ ارقام فارسی، جداکنندهٔ هزارگان و اعشار صفر پذیرفته می‌شود.",
    )
    ref_id = serializers.CharField(max_length=80, required=False, allow_blank=True)
    occurred_at = serializers.CharField(max_length=40, required=False, allow_blank=True)
    card_pan_masked = serializers.CharField(max_length=32, required=False, allow_blank=True)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)


class SettlementIngestSerializer(serializers.Serializer[dict[str, Any]]):
    """بدنهٔ ورود یک صورت‌حساب تسویهٔ درگاه."""

    gateway_name = serializers.ChoiceField(
        # فقط دو درگاهی که صورت‌حساب تسویه دارند. مقدارها عیناً برابر
        # ``GatewayName`` هستند تا مصرف‌کننده‌ای که تایپ `gateway_name` را
        # از جای دیگر گرفته، همین‌جا هم همان اتحادیه را ببیند.
        choices=[
            ("sandbox", "درگاه تعاملی آزمایشی (Sandbox)"),
            ("zarinpal", "درگاه پرداخت زرین‌پال"),
        ],
        help_text="درگاهی که این صورت‌حساب به آن تعلق دارد.",
    )
    source_kind = serializers.ChoiceField(
        choices=[("csv", "CSV"), ("xlsx", "اکسل"), ("api", "API"), ("manual", "دستی")],
        default="manual",
    )
    period_start = serializers.DateTimeField(
        help_text="شروع بازهٔ پوشش — باید از خود فایل بیاید، نه از ساعت اکنون."
    )
    period_end = serializers.DateTimeField(help_text="پایان بازهٔ پوشش.")
    declared_total_rial = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="جمع ریالی که خود فایل ادعا می‌کند؛ اگر با محاسبهٔ ما نخواند، سند معیوب علامت می‌خورد.",
    )
    original_filename = serializers.CharField(max_length=200, required=False, allow_blank=True)
    rows = SettlementRowInputSerializer(many=True, help_text="ردیف‌های صورت‌حساب.")


class SettlementStatementSerializer(serializers.Serializer[dict[str, Any]]):
    """نمای یک سند صورت‌حساب تسویه."""

    id = serializers.UUIDField()
    gateway_name = serializers.ChoiceField(
        choices=["sandbox", "zarinpal", "idpay", "nextpay", "manual"]
    )
    source_kind = serializers.ChoiceField(choices=["csv", "xlsx", "api", "manual"])
    status = serializers.ChoiceField(
        choices=["received", "parsed", "reconciling", "reconciled", "failed"]
    )
    original_filename = serializers.CharField()
    period_start = serializers.DateTimeField()
    period_end = serializers.DateTimeField()
    row_count = serializers.IntegerField()
    declared_total_rial = serializers.IntegerField()
    computed_total_rial = serializers.IntegerField()
    integrity_ok = serializers.BooleanField(
        help_text="آیا جمع اعلامی فایل با جمع محاسبه‌شده از ردیف‌ها برابر است."
    )
    integrity_note = serializers.CharField()
    statement_sha256 = serializers.CharField(
        help_text="اثر انگشت محتوا؛ ورود دوبارهٔ همان فایل، همان سند را برمی‌گرداند."
    )
    created_at = serializers.DateTimeField()


class SettlementRowSerializer(serializers.Serializer[dict[str, Any]]):
    """نمای یک ردیف صورت‌حساب و نتیجهٔ تطبیق آن."""

    id = serializers.UUIDField()
    row_number = serializers.IntegerField()
    authority = serializers.CharField()
    ref_id = serializers.CharField()
    amount_rial = serializers.IntegerField()
    occurred_at = serializers.DateTimeField(allow_null=True)
    # چرا literal و نه ``SettlementRowMatchStatus.choices``؟
    #   چون ``core`` بر اساس گیت AST پروژه هرگز نباید از ``contributions``
    #   ایمپورت کند (``contributions`` به ``core`` وابسته است، نه برعکس).
    #   همان الگویی که برای ``gateway_name`` در v1.3.0 پذیرفته شد: فهرست
    #   صریح + یک تست قرارداد که همگامی با enum واقعی را قفل می‌کند
    #   (``test_contract_status_enums_match_model_choices``).
    match_status = serializers.ChoiceField(
        choices=[
            "pending",
            "matched",
            "duplicate_in_file",
            "missing_internal",
            "amount_mismatch",
            "internal_not_verified",
            "missing_gateway",
        ],
        help_text="نتیجهٔ تطبیق این ردیف با دفتر داخلی.",
    )
    match_note = serializers.CharField(
        help_text="توضیح فارسی نتیجه — برای نمایش مستقیم به اپراتور."
    )
    payment_id = serializers.UUIDField(allow_null=True)
    remediation = serializers.CharField(help_text="اقدام انجام‌شده یا تجویزشده.")
    remediation_note = serializers.CharField()


class SettlementReconciliationSerializer(serializers.Serializer[dict[str, Any]]):
    """نتیجهٔ یک اجرای تطبیق روی یک صورت‌حساب."""

    id = serializers.UUIDField()
    statement_id = serializers.UUIDField()
    matched_count = serializers.IntegerField()
    amount_mismatch_count = serializers.IntegerField()
    missing_internal_count = serializers.IntegerField(
        help_text="تعداد ردیف‌هایی که در صورتحساب هستند ولی پرداخت داخلی ندارند (پول بی‌مالک)."
    )
    missing_gateway_count = serializers.IntegerField(
        help_text="پرداخت‌های تأییدشدهٔ داخلی که در صورتحساب درگاه غایب‌اند."
    )
    internal_not_verified_count = serializers.IntegerField(
        help_text="پرداخت‌هایی که درگاه پول آن‌ها را گرفته ولی داخلی تأیید نشده‌اند."
    )
    duplicate_in_file_count = serializers.IntegerField()
    auto_healed_count = serializers.IntegerField()
    queued_review_count = serializers.IntegerField()
    financial_impact_rial = serializers.IntegerField(
        help_text="اثر ریالی خالص: مثبت = پول پیدا شد که در دفتر نبود، منفی = دفتری که پشتوانه ندارد."
    )
    is_clean = serializers.BooleanField()
    created_at = serializers.DateTimeField()


class ReconciliationStatsSerializer(serializers.Serializer[dict[str, Any]]):
    """آمار خام یک اجرای تطبیق (هم برای dry_run و هم اجرای واقعی)."""

    matched = serializers.IntegerField()
    amount_mismatch = serializers.IntegerField()
    missing_internal = serializers.IntegerField()
    missing_gateway = serializers.IntegerField()
    internal_not_verified = serializers.IntegerField()
    duplicate_in_file = serializers.IntegerField()
    financial_impact_rial = serializers.IntegerField()


class RemediationOutcomeSerializer(serializers.Serializer[dict[str, Any]]):
    """نتیجهٔ اجرای مرحلهٔ اقدام روی یک صورت‌حساب."""

    statement_id = serializers.CharField()
    auto_healed = serializers.IntegerField(help_text="تعداد پرونده‌هایی که خودکار درمان شدند.")
    queued_review = serializers.IntegerField(help_text="تعداد پرونده‌های ارجاع‌شده به انسان.")
    blocked = serializers.IntegerField(help_text="تعداد اقدام‌های مسدودشده به‌دلیل نقض صحت سند.")
    skipped = serializers.IntegerField()
    already_resolved = serializers.IntegerField()
    heal_details = serializers.ListField(
        child=serializers.DictField(), help_text="جزئیات هر خوددرمانی برای ممیزی."
    )
