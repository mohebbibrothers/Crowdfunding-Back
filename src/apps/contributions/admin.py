"""ثبت مدل‌های مشارکت، پرداخت، نیت‌نامه، رسید و مرکل در ادمین جنگو."""

from __future__ import annotations

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.html import format_html

from apps.contributions.models import (
    AmbassadorLink,
    CampaignTransparencySnapshot,
    Contribution,
    DedicationCard,
    DonationReceipt,
    ExternalContribution,
    LateCaptureRecovery,
    Payment,
    PaymentRefund,
    SettlementReconciliation,
    SettlementRow,
    SettlementStatement,
)
from apps.contributions.services import settle_refund_obligation


@admin.register(Contribution)
class ContributionAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "id",
        "user",
        "target_kind",
        "shares_count",
        "amount_rial",
        "status",
        "created_at",
    )
    list_filter = ("target_kind", "status", "is_anonymous")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("authority", "gateway_name", "amount_rial", "status", "ref_id", "verified_at")
    list_filter = ("gateway_name", "status")


@admin.register(PaymentRefund)
class PaymentRefundAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """پنل بازپرداخت‌ها با اکشن «تسویه» برای بستن رسمی تعهد بدهی."""

    list_display = (
        "payment",
        "amount_rial",
        "outcome",
        "attempt_count",
        "gateway_reference",
        "created_at",
    )
    list_filter = ("outcome", "attempt_count")
    search_fields = ("payment__authority", "gateway_reference", "bank_reference")
    readonly_fields = ("gateway_raw_code", "attempt_count", "last_attempt_at", "automation_note")
    actions = ("settle_selected_refunds",)

    @admin.action(description="✅ تسویه بازپرداخت‌های انتخاب‌شده و بستن تعهد بدهی")
    def settle_selected_refunds(
        self, request: HttpRequest, queryset: QuerySet[PaymentRefund]
    ) -> None:
        """نهایی‌سازی بازپرداخت‌هایی که بانک/درگاه پرداخت را تأیید کرده است."""
        settled = 0
        actor = request.user if request.user.is_authenticated else None
        for refund in queryset.select_related("payment"):
            settle_refund_obligation(
                refund_id=refund.pk,
                actor=actor,  # type: ignore[arg-type]
                bank_reference=refund.gateway_reference or refund.bank_reference,
                note="تسویه از پنل مدیریت",
            )
            settled += 1
        self.message_user(
            request, f"{settled} بازپرداخت تسویه و تعهد بدهی آن بسته شد.", messages.SUCCESS
        )


@admin.register(LateCaptureRecovery)
class LateCaptureRecoveryAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """پنل «سلامت مالی حلقهٔ وجه» — هر پرداخت رهاشده و سرنوشت آن."""

    list_display = (
        "payment",
        "outcome",
        "decision_reason",
        "capacity_at_decision",
        "recovered_shares",
        "attempt_count",
        "resolved_at",
        "created_at",
    )
    list_filter = ("outcome", "decision_reason")
    search_fields = ("payment__authority", "gateway_ref_id", "decision_reason")
    readonly_fields = ("gateway_verdict_raw", "last_error", "status_badge")
    date_hierarchy = "created_at"

    @admin.display(description="وضعیت")
    def status_badge(self, obj: LateCaptureRecovery) -> str:
        """نشان رنگی وضعیت داوری برای خوانایی سریع در پنل عملیات."""
        palette = {
            "recovered": ("#0f766e", "#ccfbf1"),
            "refund_pending": ("#b45309", "#fef3c7"),
            "not_captured": ("#334155", "#f1f5f9"),
            "manual_review": ("#b91c1c", "#fee2e2"),
        }
        fg, bg = palette.get(str(obj.outcome), ("#334155", "#f1f5f9"))
        return format_html(
            '<span style="background:{};color:{};padding:2px 8px;border-radius:999px;'
            'font-weight:600">{}</span>',
            bg,
            fg,
            obj.get_outcome_display(),
        )


@admin.register(ExternalContribution)
class ExternalContributionAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "campaign",
        "shares_count",
        "amount_rial",
        "donor_display_name",
        "reference_code",
    )


@admin.register(DedicationCard)
class DedicationCardAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("public_token", "dedication_type", "honoree_name", "is_active", "created_at")


@admin.register(AmbassadorLink)
class AmbassadorLinkAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "code",
        "user",
        "click_count",
        "referred_donors_count",
        "attributed_amount_rial",
    )


@admin.register(DonationReceipt)
class DonationReceiptAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("receipt_number", "verification_code", "contribution", "created_at")


@admin.register(CampaignTransparencySnapshot)
class CampaignTransparencySnapshotAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("campaign", "leaf_count", "merkle_root", "created_at")


# ══════════════════════════════════════════════════════════════════════════════
# لایهٔ حقیقت وجه — پنل ادمین صورت‌حساب تسویه
# ══════════════════════════════════════════════════════════════════════════════


@admin.register(SettlementStatement)
class SettlementStatementAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """سند صورت‌حساب تسویه — «چشم مستقل» سامانه.

    اکشن «تطبیق» عمداً ``dry_run`` اجرا می‌کند: مدیر باید اول ببیند چه چیزی
    کشف می‌شود، بعد تصمیم بگیرد. اکشن «خوددرمانی» فقط پس از تطبیق معنادار است
    و همان موتور داوری موجود را صدا می‌زند.
    """

    list_display = (
        "gateway_name",
        "period_start",
        "period_end",
        "row_count",
        "computed_total_rial",
        "integrity_flag",
        "status",
        "created_at",
    )
    list_filter = ("gateway_name", "status", "integrity_ok")
    search_fields = ("statement_sha256", "original_filename")
    date_hierarchy = "period_end"
    ordering = ("-period_end",)
    readonly_fields = (
        "statement_sha256",
        "computed_total_rial",
        "row_count",
        "created_at",
        "updated_at",
    )
    actions = ["action_reconcile_dry_run", "action_remediate_auto_heal"]

    @admin.display(description="صحت سند", boolean=True)
    def integrity_flag(self, obj: SettlementStatement) -> bool:
        """آیا جمع اعلامی فایل با جمع محاسبه‌شده از ردیف‌ها برابر است."""
        return bool(obj.integrity_ok)

    @admin.action(description="اجرای تطبیق سه‌طرفه (پیش‌نمایش بدون نوشتن)")
    def action_reconcile_dry_run(
        self, request: HttpRequest, queryset: QuerySet[SettlementStatement]
    ) -> None:
        """تطبیق آزمایشی هر سند انتخاب‌شده و نمایش خلاصه در پیام ادمین."""
        from apps.contributions.settlement import reconcile_settlement_statement

        total_findings = 0
        for statement in queryset:
            _result, stats = reconcile_settlement_statement(
                statement_id=statement.pk, actor=request.user, dry_run=True
            )
            total_findings += stats.total_discrepancies
        self.message_user(
            request,
            f"پیش‌نمایش تطبیق انجام شد: {queryset.count()} سند، "
            f"{total_findings} مغایرت کشف‌شده (هیچ تغییری نوشته نشد).",
            messages.SUCCESS,
        )

    @admin.action(description="خوددرمانی خودکار مجاز (فقط پرداخت اثبات‌نشدهٔ زیر سقف)")
    def action_remediate_auto_heal(
        self, request: HttpRequest, queryset: QuerySet[SettlementStatement]
    ) -> None:
        """اجرای اقدام خودکار مجاز روی اسناد انتخاب‌شده با ثبت نتیجه در پیام."""
        from apps.contributions.settlement import remediate_settlement_statement

        healed = 0
        queued = 0
        blocked = 0
        for statement in queryset:
            outcome = remediate_settlement_statement(
                statement_id=statement.pk, actor=request.user, dry_run=False
            )
            healed += outcome.auto_healed
            queued += outcome.queued_review
            blocked += outcome.blocked
        level = messages.WARNING if blocked else messages.SUCCESS
        self.message_user(
            request,
            f"اقدام انجام شد: {healed} خوددرمانی، {queued} ارجاع به بررسی انسانی، "
            f"{blocked} مسدودشده به‌دلیل نقض صحت سند.",
            level,
        )


@admin.register(SettlementRow)
class SettlementRowAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """ردیف‌های صورت‌حساب با نتیجهٔ تطبیق و اقدام — برای ریشه‌یابی سریع."""

    list_display = (
        "row_number",
        "statement",
        "authority",
        "amount_rial",
        "match_status",
        "remediation",
        "payment",
    )
    list_filter = ("match_status", "remediation", "statement__gateway_name")
    search_fields = ("authority", "ref_id")
    raw_id_fields = ("statement", "payment")
    readonly_fields = (
        "match_status",
        "match_note",
        "remediation",
        "remediation_note",
        "remediated_at",
        "raw_payload",
    )
    ordering = ("statement", "row_number")


@admin.register(SettlementReconciliation)
class SettlementReconciliationAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """تاریخچهٔ اجرای تطبیق — عکس فوری قابل ممیزی هر اجرا."""

    list_display = (
        "statement",
        "matched_count",
        "missing_internal_count",
        "amount_mismatch_count",
        "financial_impact_rial",
        "is_clean",
        "created_at",
    )
    list_filter = ("is_clean", "dry_run")
    readonly_fields = [f.name for f in SettlementReconciliation._meta.fields]
    ordering = ("-created_at",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        """رکورد تطبیق فقط توسط موتور ساخته می‌شود، نه دستی."""
        del request
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: SettlementReconciliation | None = None
    ) -> bool:
        """تغییر نتیجهٔ تطبیق ممنوع است — این رکورد شاهد ممیزی است."""
        del request, obj
        return False
