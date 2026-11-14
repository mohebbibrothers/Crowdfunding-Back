"""ثبت مدل‌های عملیاتی هستهٔ مشترک (Outbox و Policy) در پنل مدیریت جنگو."""

from __future__ import annotations

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.core.models import IdempotencyRecord, OutboxMessage, PolicyRevision, PolicyRule
from apps.core.outbox import requeue_outbox_messages


@admin.register(OutboxMessage)
class OutboxMessageAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """نمای پایش و نجات پیام‌های صندوق خروجی در پنل جنگو."""

    list_display = ("event_type", "status", "attempts", "available_at", "created_at")
    list_filter = ("status", "event_type")
    search_fields = ("aggregate_id", "dedup_key", "last_error")
    readonly_fields = ("created_at", "updated_at", "processed_at")
    actions = ("requeue_dead_messages",)

    @admin.action(description="🔁 بازگردانی پیام‌های متوقف‌شده (DEAD) به صف ارسال")
    def requeue_dead_messages(
        self, request: HttpRequest, queryset: QuerySet[OutboxMessage]
    ) -> None:
        """بازگردانی امن پیام‌های DEAD به صف بدون هیچ دست‌کاری مستقیم در دیتابیس.

        این اکشن جایگزین رسمی «UPDATE دستی روی جدول» است؛ شمارندهٔ تلاش را صفر
        می‌کند و کنش حسابرسانه ثبت می‌کند تا معلوم باشد چه کسی و چه زمانی نجات داد.
        """
        ids = list(queryset.values_list("id", flat=True))
        stats = requeue_outbox_messages(message_ids=ids)
        if stats["requeued"]:
            from apps.audit.choices import AuditAction
            from apps.audit.services import record_audit_event

            record_audit_event(
                action=AuditAction.OUTBOX_MESSAGE_REQUEUED,
                actor=request.user,
                target_type="OutboxMessage",
                target_id=",".join(stats["requeued_ids"])[:200],
                reason="بازگردانی گروهی پیام متوقف‌شده از پنل مدیریت",
                metadata={"count": stats["requeued"]},
                request=request,
            )
        if stats["requeued"]:
            self.message_user(
                request,
                f"{stats['requeued']} پیام متوقف‌شده به صف ارسال بازگردانده شد.",
                messages.SUCCESS,
            )
        if stats["skipped"]:
            self.message_user(
                request,
                f"{stats['skipped']} پیام در وضعیت DEAD نبود و نادیده گرفته شد.",
                messages.WARNING,
            )


@admin.register(PolicyRule)
class PolicyRuleAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """نمای مشاهدهٔ سیاست‌های سامانه در پنل جنگو."""

    list_display = ("key", "value_type", "raw_value", "version", "updated_at")
    readonly_fields = (
        "key",
        "value_type",
        "raw_value",
        "version",
        "updated_by_id",
        "created_at",
        "updated_at",
    )


@admin.register(PolicyRevision)
class PolicyRevisionAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """نمای تاریخچهٔ نسخه‌های سیاست‌ها."""

    list_display = ("policy", "version", "reason", "created_at")
    readonly_fields = (
        "policy",
        "version",
        "previous_value",
        "new_value",
        "reason",
        "changed_by_id",
        "created_at",
    )


@admin.register(IdempotencyRecord)
class IdempotencyRecordAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """نمای پایش کلیدهای هم‌توانی."""

    list_display = ("scope", "key", "actor_ref", "response_status", "expires_at")
    readonly_fields = (
        "key",
        "scope",
        "actor_ref",
        "request_fingerprint",
        "response_status",
        "response_body",
    )
