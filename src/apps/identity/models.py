"""مدل‌های هویت: کاربر تلفن‌محور، چالش OTP، رجیستری نشست دوگانه، TOTP کارکنان و سیگنال ریسک."""

from __future__ import annotations

from typing import Any, ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.crypto import (
    blind_index,
    decrypt_value,
    encrypt_value,
    mask_national_code,
    mask_phone,
)
from apps.core.models import BaseModel
from apps.core.uuid7 import uuid7
from apps.identity.choices import AuthRiskType, OtpPurpose, RiskReviewStatus, UserRole
from apps.identity.validators import normalize_phone

NATIONAL_CODE_NAMESPACE = "identity.national_code"
RECOVERY_CODE_NAMESPACE = "identity.recovery_code"


class UserManager(BaseUserManager["User"]):
    """مدیر اختصاصی ساخت کاربر تلفن‌محور و سوپریوزر."""

    def create_user(
        self,
        phone: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> User:
        """ایجاد کاربر عادی یا کارمند با شماره تلفن نرمال‌شده."""
        normalized = normalize_phone(phone)
        user = self.model(phone=normalized, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        phone: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> User:
        """ایجاد مدیر ارشد سامانه از خط فرمان."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", UserRole.SUPER_ADMIN)
        return self.create_user(phone=phone, password=password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """مدل کاربر تلفن‌محور با رمزنگاری کد ملی در سکون و نقش‌های چهارگانه."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, verbose_name=_("شناسه"))
    phone = models.CharField(
        max_length=20, unique=True, db_index=True, verbose_name=_("شماره موبایل")
    )
    first_name = models.CharField(max_length=80, blank=True, default="", verbose_name=_("نام"))
    last_name = models.CharField(
        max_length=80, blank=True, default="", verbose_name=_("نام خانوادگی")
    )
    national_code_encrypted = models.CharField(
        max_length=255, blank=True, default="", verbose_name=_("کد ملی رمزنگاری‌شده")
    )
    national_code_index = models.CharField(
        max_length=64, blank=True, default="", db_index=True, verbose_name=_("ایندکس کور کد ملی")
    )
    province = models.CharField(max_length=80, blank=True, default="", verbose_name=_("استان"))
    city = models.CharField(max_length=80, blank=True, default="", verbose_name=_("شهر"))
    role = models.CharField(
        max_length=24,
        choices=UserRole.choices,
        default=UserRole.DONOR,
        db_index=True,
        verbose_name=_("نقش"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("فعال"))
    is_staff = models.BooleanField(default=False, verbose_name=_("دسترسی پنل جنگو"))
    created_at = models.DateTimeField(
        default=timezone.now, db_index=True, verbose_name=_("زمان ثبت‌نام")
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("آخرین ویرایش"))

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        verbose_name = _("کاربر")
        verbose_name_plural = _("کاربران")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        """نمایش امن کاربر."""
        return f"{self.display_name} ({self.masked_phone})"

    @property
    def full_name(self) -> str:
        """نام و نام خانوادگی ترکیب‌شده."""
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def display_name(self) -> str:
        """نام نمایشی خیر؛ در صورت عدم تکمیل پروفایل «نیکوکار گرامی» برمی‌گرداند."""
        return self.full_name or "نیکوکار گرامی"

    @property
    def masked_phone(self) -> str:
        """شماره موبایل پوشانده‌شده برای نمایش پیش‌فرض."""
        return mask_phone(self.phone)

    @property
    def is_staff_member(self) -> bool:
        """آیا کاربر عضو تیم عملیاتی/مالی/مدیریت است؟"""
        return bool(
            self.is_superuser
            or self.is_staff
            or self.role in {UserRole.OPERATOR, UserRole.FINANCE_MANAGER, UserRole.SUPER_ADMIN}
        )

    @property
    def is_finance_or_super(self) -> bool:
        """آیا کاربر دارای سطح دسترسی مدیر مالی یا مدیر ارشد است؟"""
        return bool(
            self.is_superuser or self.role in {UserRole.FINANCE_MANAGER, UserRole.SUPER_ADMIN}
        )

    @property
    def is_profile_complete(self) -> bool:
        """آیا کاربر نام و نام خانوادگی خود را تکمیل کرده است؟"""
        return bool(self.first_name.strip() and self.last_name.strip())

    def set_national_code(self, raw_code: str) -> None:
        """رمزنگاری AES-GCM کد ملی و محاسبهٔ ایندکس کور HMAC."""
        if not raw_code:
            self.national_code_encrypted = ""
            self.national_code_index = ""
            return
        self.national_code_encrypted = encrypt_value(raw_code)
        self.national_code_index = blind_index(raw_code, namespace=NATIONAL_CODE_NAMESPACE)

    def get_national_code_masked(self) -> str:
        """برگرداندن نمای پوشانده‌شدهٔ کد ملی (فقط ۴ رقم آخر)."""
        plain = decrypt_value(self.national_code_encrypted)
        return mask_national_code(plain)


class OtpChallenge(BaseModel):
    """چالش کد یک‌بارمصرف پیامکی با ذخیره‌سازی صرفاً هش نمک‌دار (Salted HMAC)."""

    phone = models.CharField(max_length=20, db_index=True, verbose_name=_("شماره موبایل"))
    purpose = models.CharField(
        max_length=24,
        choices=OtpPurpose.choices,
        default=OtpPurpose.LOGIN,
        verbose_name=_("هدف"),
    )
    salt = models.CharField(max_length=32, verbose_name=_("نمک تصادفی"))
    code_digest = models.CharField(max_length=64, verbose_name=_("هش کد"))
    attempts = models.PositiveSmallIntegerField(default=0, verbose_name=_("تعداد تلاش"))
    max_attempts = models.PositiveSmallIntegerField(default=5, verbose_name=_("سقف تلاش"))
    expires_at = models.DateTimeField(db_index=True, verbose_name=_("زمان انقضا"))
    consumed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("زمان مصرف"))
    requester_ip = models.GenericIPAddressField(null=True, blank=True, verbose_name=_("آدرس IP"))

    class Meta:
        verbose_name = _("چالش کد یک‌بارمصرف")
        verbose_name_plural = _("چالش‌های کد یک‌بارمصرف")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["phone", "purpose", "-created_at"], name="ident_otp_lookup_idx"),
        ]

    def __str__(self) -> str:
        """نمایش شمارهٔ پوشانده و وضعیت مصرف."""
        return f"OTP {mask_phone(self.phone)} [{self.purpose}]"


class UserSession(BaseModel):
    """رجیستری یکپارچهٔ نشست‌های فعال کاربر (هم کوکی HttpOnly و هم SessionAwareJWT)."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="sessions",
        verbose_name=_("کاربر"),
    )
    session_key = models.CharField(
        max_length=64, blank=True, default="", db_index=True, verbose_name=_("کلید نشست کوکی")
    )
    refresh_jti = models.CharField(
        max_length=64, unique=True, db_index=True, verbose_name=_("شناسهٔ چرخشی Refresh")
    )
    device_label = models.CharField(
        max_length=80, blank=True, default="مرورگر", verbose_name=_("دستگاه")
    )
    network_prefix = models.CharField(
        max_length=64, blank=True, default="", verbose_name=_("پیشوند شبکه")
    )
    last_seen_at = models.DateTimeField(default=timezone.now, verbose_name=_("آخرین فعالیت"))
    mfa_verified_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("زمان تأیید دومرحله‌ای")
    )
    mfa_method = models.CharField(
        max_length=16, blank=True, default="", verbose_name=_("روش عامل دوم")
    )
    revoked_at = models.DateTimeField(
        null=True, blank=True, db_index=True, verbose_name=_("زمان ابطال")
    )

    class Meta:
        verbose_name = _("نشست کاربر")
        verbose_name_plural = _("نشست‌های کاربران")
        ordering = ["-last_seen_at"]
        indexes = [
            models.Index(
                fields=["user", "revoked_at", "-last_seen_at"], name="ident_sess_active_idx"
            ),
        ]

    def __str__(self) -> str:
        """نمایش کاربر و برچسب دستگاه."""
        return f"{self.user.masked_phone} · {self.device_label}"

    @property
    def is_active_session(self) -> bool:
        """آیا نشست فعال و باطل‌نشده است؟"""
        return self.revoked_at is None and self.deleted_at is None


class StaffTotpDevice(BaseModel):
    """دستگاه احراز هویت دومرحله‌ای (TOTP) مخصوص کارکنان و مدیران."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="totp_device",
        verbose_name=_("کارمند"),
    )
    secret_encrypted = models.CharField(max_length=255, verbose_name=_("راز رمزنگاری‌شده"))
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("زمان تأیید نهایی"))

    class Meta:
        verbose_name = _("دستگاه TOTP کارمند")
        verbose_name_plural = _("دستگاه‌های TOTP کارکنان")

    def __str__(self) -> str:
        """نمایش وضعیت دستگاه TOTP."""
        state = "فعال" if self.confirmed_at else "در انتظار تأیید"
        return f"TOTP({self.user.masked_phone}) [{state}]"


class StaffRecoveryCode(BaseModel):
    """کدهای بازیابی یک‌بارمصرف کارکنان (ذخیره‌شده با ایندکس کور HMAC)."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="recovery_codes",
        verbose_name=_("کارمند"),
    )
    code_hash = models.CharField(max_length=64, db_index=True, verbose_name=_("هش کد بازیابی"))
    used_at = models.DateTimeField(null=True, blank=True, verbose_name=_("زمان مصرف"))

    class Meta:
        verbose_name = _("کد بازیابی عامل دوم")
        verbose_name_plural = _("کدهای بازیابی عامل دوم")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "code_hash"], name="uniq_ident_staff_recovery_hash"
            ),
        ]

    def __str__(self) -> str:
        """نمایش وضعیت مصرف کد بازیابی."""
        return f"Recovery({self.user_id}) used={bool(self.used_at)}"


class AuthRiskSignal(BaseModel):
    """سیگنال‌های ریسک امنیتی تشخیص‌داده‌شده در فرآیند ورود، OTP یا چرخش توکن."""

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="auth_risk_signals",
        verbose_name=_("کاربر"),
    )
    signal_type = models.CharField(
        max_length=40, choices=AuthRiskType.choices, db_index=True, verbose_name=_("نوع سیگنال")
    )
    status = models.CharField(
        max_length=20,
        choices=RiskReviewStatus.choices,
        default=RiskReviewStatus.OPEN,
        db_index=True,
        verbose_name=_("وضعیت بررسی"),
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name=_("آدرس IP"))
    phone_masked = models.CharField(
        max_length=24, blank=True, default="", verbose_name=_("تلفن پوشانده")
    )
    metadata = models.JSONField(default=dict, blank=True, verbose_name=_("جزئیات"))
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_auth_risks",
        verbose_name=_("بررسی‌کننده"),
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("زمان بررسی"))
    review_note = models.CharField(
        max_length=400, blank=True, default="", verbose_name=_("یادداشت بررسی")
    )

    class Meta:
        verbose_name = _("سیگنال ریسک هویت")
        verbose_name_plural = _("سیگنال‌های ریسک هویت")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        """نمایش نوع سیگنال و وضعیت."""
        return f"{self.signal_type} [{self.status}]"
