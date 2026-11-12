"""ثبت مدل‌های عملیاتی هستهٔ مشترک (Outbox و Policy) در پنل مدیریت جنگو."""

from __future__ import annotations

from django.contrib import admin

from apps.core.models import IdempotencyRecord, OutboxMessage, PolicyRevision, PolicyRule


@admin.register(OutboxMessage)
class OutboxMessageAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """نمای پایش پیام‌های صندوق خروجی در پنل جنگو."""

    list_display = ("event_type", "status", "attempts", "available_at", "created_at")
    list_filter = ("status", "event_type")
    search_fields = ("aggregate_id", "dedup_key", "last_error")
    readonly_fields = ("created_at", "updated_at", "processed_at")


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
