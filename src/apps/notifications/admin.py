"""ثبت مدل‌های اعلان و لاگ پیامک در پنل مدیریت جنگو."""

from __future__ import annotations

from django.contrib import admin

from apps.notifications.models import SmsDeliveryLog, UserNotification


@admin.register(UserNotification)
class UserNotificationAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """مدیریت اعلان‌های درون‌برنامه‌ای."""

    list_display = ("user", "kind", "title", "read_at", "created_at")
    list_filter = ("kind",)


@admin.register(SmsDeliveryLog)
class SmsDeliveryLogAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """پایش دفتر ممیزی ارسال پیامک."""

    list_display = ("pattern_code", "phone_masked", "provider_name", "status", "created_at")
    list_filter = ("pattern_code", "status", "provider_name")
    readonly_fields = [f.name for f in SmsDeliveryLog._meta.fields]
