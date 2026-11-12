"""سریالایزرهای احراز هویت OTP، نشست دوگانه، پروفایل، TOTP کارکنان و مدیریت کاربران."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.core.jalali import format_jalali_datetime
from apps.identity.choices import RiskReviewStatus, UserRole


class OtpRequestInputSerializer(serializers.Serializer[dict[str, Any]]):
    """ورودی درخواست ارسال کد یک‌بارمصرف پیامکی."""

    phone = serializers.CharField(max_length=20)


class OtpRequestAcceptedSerializer(serializers.Serializer[dict[str, Any]]):
    """پاسخ یکسان ضد شمارش کاربر هنگام درخواست OTP."""

    status = serializers.CharField()
    ttl_seconds = serializers.IntegerField()
    message = serializers.CharField()


class OtpVerifyInputSerializer(serializers.Serializer[dict[str, Any]]):
    """ورودی تأیید کد ۵ رقمی پیامکی."""

    phone = serializers.CharField(max_length=20)
    code = serializers.CharField(max_length=10)


class StaffPasswordLoginInputSerializer(serializers.Serializer[dict[str, Any]]):
    """ورودی ورود کارکنان با گذرواژه."""

    phone = serializers.CharField(max_length=20)
    password = serializers.CharField(max_length=128, trim_whitespace=False)


class TokenRefreshInputSerializer(serializers.Serializer[dict[str, Any]]):
    """ورودی نوسازی چرخشی توکن دسترسی."""

    refresh_token = serializers.CharField()


class UserMeOutputSerializer(serializers.Serializer[Any]):
    """نمای پروفایل کاربر جاری."""

    id = serializers.UUIDField()
    phone = serializers.CharField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    display_name = serializers.CharField()
    national_code_masked = serializers.SerializerMethodField()
    province = serializers.CharField()
    city = serializers.CharField()
    role = serializers.ChoiceField(choices=UserRole.choices)
    is_profile_complete = serializers.BooleanField()
    is_staff_member = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    created_at_jalali = serializers.SerializerMethodField()

    def get_national_code_masked(self, obj: Any) -> str:
        """نمایش پوشاندهٔ کد ملی."""
        return str(obj.get_national_code_masked())

    def get_created_at_jalali(self, obj: Any) -> str | None:
        """تاریخ عضویت به شمسی."""
        return format_jalali_datetime(obj.created_at)


class AuthTokensOutputSerializer(serializers.Serializer[dict[str, Any]]):
    """پاسخ ورود موفق شامل نشست، توکن‌های JWT و وضعیت MFA."""

    access_token = serializers.CharField()
    refresh_token = serializers.CharField()
    session_id = serializers.UUIDField()
    mfa_required = serializers.BooleanField()
    user = UserMeOutputSerializer()


class ProfileUpdateInputSerializer(serializers.Serializer[dict[str, Any]]):
    """ورودی ویرایش مشخصات پروفایل خیر."""

    first_name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    national_code = serializers.CharField(max_length=16, required=False, allow_blank=True)
    province = serializers.CharField(max_length=80, required=False, allow_blank=True)
    city = serializers.CharField(max_length=80, required=False, allow_blank=True)


class SessionItemOutputSerializer(serializers.Serializer[Any]):
    """نمای یک نشست فعال در فهرست دستگاه‌های کاربر."""

    id = serializers.UUIDField()
    device = serializers.CharField()
    network = serializers.CharField()
    mfa_verified = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    last_seen_at = serializers.DateTimeField()
    is_current = serializers.BooleanField()


class MfaStatusOutputSerializer(serializers.Serializer[dict[str, Any]]):
    """وضعیت عامل دوم کارمند."""

    enrolled = serializers.BooleanField()
    session_verified = serializers.BooleanField()
    verified_at = serializers.DateTimeField(allow_null=True)
    remaining_recovery_codes = serializers.IntegerField()


class MfaSetupOutputSerializer(serializers.Serializer[dict[str, Any]]):
    """خروجی مرحلهٔ راه‌اندازی TOTP شامل QR برداری."""

    secret = serializers.CharField()
    otpauth_uri = serializers.CharField()
    qr_svg = serializers.CharField()


class MfaCodeInputSerializer(serializers.Serializer[dict[str, Any]]):
    """ورودی کد ۶ رقمی TOTP یا کد بازیابی."""

    code = serializers.CharField(max_length=20)


class MfaConfirmOutputSerializer(serializers.Serializer[dict[str, Any]]):
    """خروجی تأیید نهایی TOTP شامل ۱۰ کد بازیابی یک‌بارمصرف."""

    enrolled = serializers.BooleanField()
    recovery_codes = serializers.ListField(child=serializers.CharField())


class AdminUserOutputSerializer(serializers.Serializer[Any]):
    """نمای کاربر برای میز عملیاتی ادمین (با شماره تلفن پوشانده در حالت عادی)."""

    id = serializers.UUIDField()
    masked_phone = serializers.CharField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    display_name = serializers.CharField()
    province = serializers.CharField()
    city = serializers.CharField()
    role = serializers.ChoiceField(choices=UserRole.choices)
    is_active = serializers.BooleanField()
    created_at = serializers.DateTimeField()


class AdminRoleChangeInputSerializer(serializers.Serializer[dict[str, Any]]):
    """ورودی تغییر نقش کاربری با الزام دلیل."""

    role = serializers.ChoiceField(choices=UserRole.choices)
    reason = serializers.CharField(min_length=5, max_length=400)


class AdminPhoneRevealInputSerializer(serializers.Serializer[dict[str, Any]]):
    """ورودی درخواست مشاهدهٔ شمارهٔ کامل خیر با الزام ثبت هدف."""

    reason = serializers.CharField(min_length=5, max_length=400)


class AuthRiskSignalOutputSerializer(serializers.Serializer[Any]):
    """نمای سیگنال ریسک احراز هویت."""

    id = serializers.UUIDField()
    signal_type = serializers.CharField()
    status = serializers.CharField()
    ip_address = serializers.CharField(allow_null=True)
    phone_masked = serializers.CharField()
    metadata = serializers.JSONField()
    review_note = serializers.CharField()
    created_at = serializers.DateTimeField()


class AuthRiskReviewInputSerializer(serializers.Serializer[dict[str, Any]]):
    """ورودی بررسی سیگنال ریسک هویتی."""

    status = serializers.ChoiceField(
        choices=[RiskReviewStatus.REVIEWED, RiskReviewStatus.DISMISSED]
    )
    note = serializers.CharField(max_length=400, required=False, allow_blank=True, default="")
