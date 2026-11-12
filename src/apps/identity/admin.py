"""ثبت مدل‌های هویت در پنل مدیریت جنگو با رعایت پوشاندن داده‌های حساس."""

from __future__ import annotations

from django.contrib import admin

from apps.identity.models import AuthRiskSignal, OtpChallenge, StaffTotpDevice, User, UserSession


@admin.register(User)
class UserAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """مدیریت کاربران در پنل جنگو."""

    list_display = ("masked_phone", "display_name", "role", "is_active", "created_at")
    list_filter = ("role", "is_active")
    search_fields = ("first_name", "last_name", "phone")
    readonly_fields = (
        "id",
        "national_code_encrypted",
        "national_code_index",
        "created_at",
        "updated_at",
    )


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """پایش نشست‌های کاربران."""

    list_display = (
        "user",
        "device_label",
        "network_prefix",
        "mfa_verified_at",
        "revoked_at",
        "last_seen_at",
    )
    list_filter = ("revoked_at",)
    readonly_fields = ("session_key", "refresh_jti", "created_at", "updated_at")


@admin.register(OtpChallenge)
class OtpChallengeAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """نمای فقط‌خواندنی چالش‌های OTP (بدون نمایش کد خام)."""

    list_display = ("purpose", "attempts", "expires_at", "consumed_at", "created_at")
    readonly_fields = ("phone", "salt", "code_digest", "attempts", "expires_at", "consumed_at")


@admin.register(StaffTotpDevice)
class StaffTotpDeviceAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """نمای وضعیت دستگاه‌های TOTP کارکنان."""

    list_display = ("user", "confirmed_at", "created_at")
    readonly_fields = ("secret_encrypted", "confirmed_at")


@admin.register(AuthRiskSignal)
class AuthRiskSignalAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """نمای سیگنال‌های ریسک هویتی."""

    list_display = ("signal_type", "status", "phone_masked", "ip_address", "created_at")
    list_filter = ("signal_type", "status")
