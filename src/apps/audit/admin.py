"""ثبت فقط‌خواندنی مدل‌های حسابرسی در پنل مدیریت جنگو."""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from apps.audit.models import AuditAnchor, AuditRecord


@admin.register(AuditRecord)
class AuditRecordAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """نمای فقط‌خواندنی رکوردهای زنجیرهٔ حسابرسی."""

    list_display = ("sequence", "action", "outcome", "actor_label", "target_type", "created_at")
    list_filter = ("action", "outcome", "target_type")
    search_fields = ("actor_label", "target_id", "reason", "request_id")
    readonly_fields = [f.name for f in AuditRecord._meta.fields]

    def has_add_permission(self, request: HttpRequest) -> bool:
        """ممنوعیت افزودن دستی رکورد خارج از سرویس حسابرسی."""
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """ممنوعیت ویرایش رکورد حسابرسی."""
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """ممنوعیت حذف رکورد حسابرسی."""
        return False


@admin.register(AuditAnchor)
class AuditAnchorAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """نمای فقط‌خواندنی لنگرهای امضاشده."""

    list_display = ("last_sequence", "record_count", "anchored_at")
    readonly_fields = [f.name for f in AuditAnchor._meta.fields]

    def has_add_permission(self, request: HttpRequest) -> bool:
        """ممنوعیت ساخت دستی لنگر."""
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """ممنوعیت حذف لنگر."""
        return False
