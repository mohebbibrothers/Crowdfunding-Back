"""سرویس‌های دامنهٔ هویت: OTP، نشست دوگانه، توکن چرخشی، TOTP کارکنان و حریم خصوصی."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import hmac
from importlib import import_module
import ipaddress
import logging
import secrets
from typing import Final

from django.conf import settings
from django.contrib.auth import authenticate, login as django_login, logout as django_logout
from django.core.cache import cache
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone
from django.utils.crypto import salted_hmac
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit.choices import AuditAction, AuditOutcome
from apps.audit.services import AuditEntry, record_audit
from apps.core.crypto import blind_index, decrypt_value, encrypt_value, mask_phone
from apps.core.errors import (
    AuthenticationRequiredError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    ResourceExpiredError,
    ValidationError as DomainValidationError,
)
from apps.core.jalali import normalize_digits
from apps.core.middleware import client_ip
from apps.core.outbox import enqueue_outbox
from apps.core.uuid7 import uuid7_hex
from apps.identity import totp
from apps.identity.choices import AuthRiskType, OtpPurpose, RiskReviewStatus, UserRole
from apps.identity.models import (
    RECOVERY_CODE_NAMESPACE,
    AuthRiskSignal,
    OtpChallenge,
    StaffRecoveryCode,
    StaffTotpDevice,
    User,
    UserSession,
)
from apps.identity.validators import normalize_phone, validate_iranian_national_code

OTP_LENGTH: Final[int] = 5
logger = logging.getLogger(__name__)
OTP_TTL_SECONDS: Final[int] = 180
OTP_WINDOW_MINUTES: Final[int] = 10
OTP_MAX_PER_WINDOW: Final[int] = 4
MFA_MAX_FAILURES: Final[int] = 5
MFA_LOCKOUT_SECONDS: Final[int] = 900
RECOVERY_ALPHABET: Final[str] = "23456789ABCDEFGHJKMNPQRSTVWXYZ"  # pragma: allowlist secret
RECOVERY_COUNT: Final[int] = 10

_BROWSERS: Final[tuple[tuple[str, str], ...]] = (
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("Firefox/", "Firefox"),
    ("Chrome/", "Chrome"),
    ("Safari/", "Safari"),
)
_OS_LIST: Final[tuple[tuple[str, str], ...]] = (
    ("Android", "Android"),
    ("iPhone", "iOS"),
    ("iPad", "iPadOS"),
    ("Windows", "Windows"),
    ("Mac OS X", "macOS"),
    ("Linux", "Linux"),
)


@dataclass(frozen=True, slots=True)
class IssuedAuthTokens:
    """بستهٔ خروجی نشست صادرشده (شامل هم کوکی و هم جفت توکن JWT چرخشی)."""

    user: User
    session: UserSession
    access_token: str
    refresh_token: str
    mfa_required: bool


def extract_network_prefix(ip_text: str) -> str:
    """محاسبهٔ پیشوند شبکهٔ حریم‌خصوصی‌محور (‎/24 برای IPv4 و ‎/48 برای IPv6)."""
    try:
        ip_obj = ipaddress.ip_address(ip_text)
    except ValueError:
        return ""
    prefix = 24 if ip_obj.version == 4 else 48
    return str(ipaddress.ip_network(f"{ip_obj}/{prefix}", strict=False))


def summarize_user_agent(ua: str) -> str:
    """تبدیل رشتهٔ طولانی User-Agent به برچسب کوتاه و خوانای «مرورگر · سیستم‌عامل»."""
    browser = next((label for token, label in _BROWSERS if token in ua), "مرورگر")
    os_name = next((label for token, label in _OS_LIST if token in ua), "")
    return f"{browser} · {os_name}" if os_name else browser


def _otp_digest(*, phone: str, purpose: str, salt: str, code: str) -> str:
    return salted_hmac(
        "crowdfunding.otp",
        f"{purpose}|{phone}|{salt}|{code}",
        algorithm="sha256",
    ).hexdigest()


def _check_sms_daily_budget() -> None:
    """محافظت از بودجهٔ روزانهٔ پیامک در برابر حملات پمپاژ پیامک (SMS Pumping)."""
    budget = int(getattr(settings, "SMS_DAILY_BUDGET", 5000))
    day_key = f"sms:budget:{timezone.now().strftime('%Y%m%d')}"
    current = 0
    cache_ok = False
    try:
        current = int(cache.get(day_key) or 0)
        cache_ok = True
    except Exception:  # pragma: no cover
        logger.warning("sms_budget_cache_degraded")

    if cache_ok and current >= budget:
        raise RateLimitedError(
            "سقف ارسال پیامک لحظه‌ای سامانه پر شده است؛ کمی بعد تلاش کنید.",
            code="sms_budget_exhausted",
            extensions={"retry_after": 300},
        )
    if cache_ok:
        try:
            if not cache.add(day_key, 1, timeout=86_400):
                cache.incr(day_key)
        except Exception:  # pragma: no cover
            logger.warning("sms_budget_cache_degraded")


def request_otp(
    *,
    phone_raw: str,
    purpose: str = OtpPurpose.LOGIN,
    request: HttpRequest | None = None,
) -> tuple[OtpChallenge, str]:
    """تولید چالش OTP نمک‌دار، ثبت در صندوق خروجی پیامک و رعایت سقف ضدسوءاستفاده."""
    phone = normalize_phone(phone_raw)
    now = timezone.now()
    window_start = now - timedelta(minutes=OTP_WINDOW_MINUTES)
    recent_count = OtpChallenge.objects.filter(phone=phone, created_at__gte=window_start).count()
    if recent_count >= OTP_MAX_PER_WINDOW:
        raise RateLimitedError(
            "تعداد درخواست‌های کد تأیید برای این شماره بیش از حد مجاز است.",
            code="otp_window_exceeded",
            extensions={"retry_after": OTP_TTL_SECONDS},
        )
    _check_sms_daily_budget()

    code = f"{secrets.randbelow(90_000) + 10_000:05d}"
    salt = secrets.token_hex(16)
    digest = _otp_digest(phone=phone, purpose=purpose, salt=salt, code=code)
    ip_addr = client_ip(request) if request is not None else ""

    with transaction.atomic():
        challenge = OtpChallenge.objects.create(
            phone=phone,
            purpose=purpose,
            salt=salt,
            code_digest=digest,
            expires_at=now + timedelta(seconds=OTP_TTL_SECONDS),
            requester_ip=ip_addr or None,
        )
        enqueue_outbox(
            event_type="sms.otp_requested",
            aggregate_type="otp_challenge",
            aggregate_id=str(challenge.id),
            dedup_key=f"otp:{challenge.id}",
            payload={
                "phone": phone,
                "code": code,
                "purpose": purpose,
                "ttl_seconds": OTP_TTL_SECONDS,
            },
        )
        record_audit(
            AuditEntry(
                action=AuditAction.OTP_REQUESTED,
                target_type="phone",
                target_id=mask_phone(phone),
                metadata={"purpose": purpose},
                request=request,
            )
        )
    return challenge, code


def verify_otp_and_get_user(
    *,
    phone_raw: str,
    code_raw: str,
    purpose: str = OtpPurpose.LOGIN,
    request: HttpRequest | None = None,
) -> User:
    """بررسی اتمیک کد یک‌بارمصرف و بازگرداندن (یا ساخت خودکار) کاربر فعال."""
    phone = normalize_phone(phone_raw)
    code = normalize_digits(code_raw or "").strip()
    if len(code) != OTP_LENGTH or not code.isdigit():
        raise DomainValidationError(
            "کد تأیید باید ۵ رقم عددی باشد.",
            code="invalid_otp_code",
            errors={"code": ["کد ۵ رقمی ارسال‌شده به موبایل را وارد کنید."]},
        )

    now = timezone.now()
    with transaction.atomic():
        challenge = (
            OtpChallenge.objects.select_for_update()
            .filter(phone=phone, purpose=purpose, consumed_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if challenge is None:
            raise DomainValidationError(
                "کد تأیید معتبری یافت نشد؛ لطفاً دوباره درخواست کد بدهید.",
                code="invalid_otp_code",
                errors={"code": ["کد واردشده نامعتبر است."]},
            )
        if challenge.expires_at <= now:
            raise ResourceExpiredError(
                "مهلت استفاده از این کد به پایان رسیده است؛ کد جدید دریافت کنید.",
                code="otp_expired",
            )
        if challenge.attempts >= challenge.max_attempts:
            raise RateLimitedError(
                "سقف تلاش برای این کد تمام شده است؛ کد جدید درخواست دهید.",
                code="otp_attempts_exceeded",
                extensions={"retry_after": 60},
            )

        expected = _otp_digest(phone=phone, purpose=purpose, salt=challenge.salt, code=code)
        if not hmac.compare_digest(expected, challenge.code_digest):
            challenge.attempts += 1
            challenge.save(update_fields=["attempts", "updated_at"])
            if challenge.attempts >= challenge.max_attempts:
                AuthRiskSignal.objects.create(
                    signal_type=AuthRiskType.OTP_BRUTE_FORCE,
                    ip_address=client_ip(request) or None if request else None,
                    phone_masked=mask_phone(phone),
                    metadata={"purpose": purpose, "attempts": challenge.attempts},
                )
            raise DomainValidationError(
                "کد واردشده نادرست است.",
                code="invalid_otp_code",
                errors={"code": ["کد واردشده صحیح نیست."]},
            )

        challenge.consumed_at = now
        challenge.save(update_fields=["consumed_at", "updated_at"])

        user, _ = User.objects.get_or_create(phone=phone, defaults={"is_active": True})
        if not user.is_active:
            raise PermissionDeniedError("این حساب کاربری مسدود شده است.", code="user_inactive")

    return user


def _mint_jwt_pair(*, user: User, session_obj: UserSession) -> tuple[str, str]:
    """صدور جفت توکن Access و Refresh متصل به ردیف ``UserSession``."""
    refresh = RefreshToken.for_user(user)
    refresh["sid"] = str(session_obj.id)
    refresh["r_jti"] = session_obj.refresh_jti
    access = refresh.access_token
    access["sid"] = str(session_obj.id)
    access["role"] = user.role
    return str(access), str(refresh)


def establish_dual_session(*, user: User, request: HttpRequest) -> IssuedAuthTokens:
    """ایجاد نشست یکپارچه (هم کوکی HttpOnly چرخش‌یافته و هم جفت توکن SessionAwareJWT)."""
    ip_text = client_ip(request)
    ua_text = request.META.get("HTTP_USER_AGENT", "")[:300]
    refresh_jti = uuid7_hex()

    with transaction.atomic():
        session_obj = UserSession.objects.create(
            user=user,
            refresh_jti=refresh_jti,
            device_label=summarize_user_agent(ua_text),
            network_prefix=extract_network_prefix(ip_text),
            last_seen_at=timezone.now(),
        )
        if hasattr(request, "session"):
            django_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            request.session.cycle_key()
            request.session["user_session_id"] = str(session_obj.id)
            request.session.save()
            session_obj.session_key = request.session.session_key or ""
            session_obj.save(update_fields=["session_key", "updated_at"])

        request.active_user_session = session_obj  # type: ignore[attr-defined]
        access_token, refresh_token = _mint_jwt_pair(user=user, session_obj=session_obj)

        record_audit(
            AuditEntry(
                action=AuditAction.LOGIN_SUCCESS,
                actor_id=user.id,
                actor_label=user.display_name,
                target_type="session",
                target_id=str(session_obj.id),
                metadata={"device": session_obj.device_label},
                request=request,
            )
        )

    return IssuedAuthTokens(
        user=user,
        session=session_obj,
        access_token=access_token,
        refresh_token=refresh_token,
        mfa_required=bool(user.is_staff_member and session_obj.mfa_verified_at is None),
    )


def staff_password_login(
    *, phone_raw: str, password: str, request: HttpRequest
) -> IssuedAuthTokens:
    """ورود کارکنان با شماره موبایل و گذرواژهٔ Argon2 (پیش از گام اجباری TOTP)."""
    phone = normalize_phone(phone_raw)
    user = authenticate(request=request, username=phone, password=password)
    if not isinstance(user, User) or not user.is_active or not user.is_staff_member:
        raise AuthenticationRequiredError("شماره موبایل یا گذرواژه نادرست است.")
    return establish_dual_session(user=user, request=request)


def rotate_refresh_token(*, raw_refresh_token: str, request: HttpRequest) -> IssuedAuthTokens:
    """چرخش اتمیک توکن Refresh؛ تشخیص سرقت و ابطال آنی کل نشست در صورت استفادهٔ تکراری."""
    try:
        incoming = RefreshToken(raw_refresh_token)  # type: ignore[arg-type]
    except TokenError as exc:
        raise AuthenticationRequiredError("توکن نوسازی معتبر نیست یا منقضی شده است.") from exc

    sid = str(incoming.get("sid") or "")
    presented_rjti = str(incoming.get("r_jti") or "")
    if not sid or not presented_rjti:
        raise AuthenticationRequiredError("ساختار توکن نوسازی نامعتبر است.")

    reuse_detected = False
    minted_pair: tuple[str, str] | None = None
    with transaction.atomic():
        session_obj = (
            UserSession.objects.select_for_update().select_related("user").filter(pk=sid).first()
        )
        if (
            session_obj is None
            or session_obj.revoked_at is not None
            or not session_obj.user.is_active
        ):
            raise AuthenticationRequiredError("این نشست پایان یافته است؛ مجدداً وارد شوید.")

        if not hmac.compare_digest(session_obj.refresh_jti, presented_rjti):
            # تشخیص بازپخش توکن قدیمی ⇒ ابطال فوری نشست و ثبت سیگنال ریسک امنیتی (پیش از پرتاب استثنا ذخیره شود!)
            _delete_cookie_store(session_obj.session_key)
            session_obj.revoked_at = timezone.now()
            session_obj.save(update_fields=["revoked_at", "updated_at"])
            AuthRiskSignal.objects.create(
                user=session_obj.user,
                signal_type=AuthRiskType.REFRESH_TOKEN_REUSE,
                ip_address=client_ip(request) or None,
                phone_masked=session_obj.user.masked_phone,
                metadata={"session_id": str(session_obj.id)},
            )
            reuse_detected = True
        else:
            session_obj.refresh_jti = uuid7_hex()
            session_obj.last_seen_at = timezone.now()
            session_obj.save(update_fields=["refresh_jti", "last_seen_at", "updated_at"])
            minted_pair = _mint_jwt_pair(user=session_obj.user, session_obj=session_obj)

    if reuse_detected or minted_pair is None:
        raise AuthenticationRequiredError(
            "ناهنجاری امنیتی در توکن تشخیص داده شد؛ نشست برای حفاظت از حساب شما بسته شد."
        )

    access_val, refresh_val = minted_pair
    return IssuedAuthTokens(
        user=session_obj.user,
        session=session_obj,
        access_token=access_val,
        refresh_token=refresh_val,
        mfa_required=bool(session_obj.user.is_staff_member and session_obj.mfa_verified_at is None),
    )


def _delete_cookie_store(session_key: str) -> None:
    if not session_key:
        return
    engine = import_module(settings.SESSION_ENGINE)
    store = engine.SessionStore(session_key=session_key)
    store.delete()


def logout_current_session(
    *, user: User, session_obj: UserSession | None, request: HttpRequest
) -> None:
    """خروج از نشست جاری و ابطال هم‌زمان کوکی و JWT آن."""
    with transaction.atomic():
        if session_obj is not None and session_obj.revoked_at is None:
            _delete_cookie_store(session_obj.session_key)
            session_obj.revoked_at = timezone.now()
            session_obj.save(update_fields=["revoked_at", "updated_at"])
        if hasattr(request, "session"):
            django_logout(request)
        record_audit(
            AuditEntry(
                action=AuditAction.LOGOUT,
                actor_id=user.id,
                actor_label=user.display_name,
                target_type="session",
                target_id=str(session_obj.id) if session_obj else "",
                request=request,
            )
        )


def revoke_user_session(
    *, user: User, target_session_id: str, current_session: UserSession | None, request: HttpRequest
) -> None:
    """ابطال یک نشست مشخص از فهرست «دستگاه‌های من»."""
    row = UserSession.objects.filter(
        user=user, pk=target_session_id, revoked_at__isnull=True
    ).first()
    if row is None:
        raise NotFoundError("نشست مورد نظر یافت نشد.")
    if current_session is not None and row.pk == current_session.pk:
        raise ConflictError(
            "برای بستن نشست فعلی از مسیر خروج (logout) استفاده کنید.",
            code="cannot_revoke_current_session",
        )
    with transaction.atomic():
        _delete_cookie_store(row.session_key)
        row.revoked_at = timezone.now()
        row.save(update_fields=["revoked_at", "updated_at"])
        record_audit(
            AuditEntry(
                action=AuditAction.SESSION_REVOKED,
                actor_id=user.id,
                actor_label=user.display_name,
                target_type="session",
                target_id=str(row.id),
                metadata={"scope": "single"},
                request=request,
            )
        )


def revoke_other_sessions(
    *, user: User, current_session: UserSession | None, request: HttpRequest
) -> int:
    """خروج از تمام دستگاه‌های دیگر با حفظ نشست فعلی."""
    qs = UserSession.objects.filter(user=user, revoked_at__isnull=True)
    if current_session is not None:
        qs = qs.exclude(pk=current_session.pk)
    rows = list(qs)
    if not rows:
        return 0
    now = timezone.now()
    with transaction.atomic():
        for row in rows:
            _delete_cookie_store(row.session_key)
        UserSession.objects.filter(pk__in=[r.pk for r in rows]).update(
            revoked_at=now, updated_at=now
        )
        record_audit(
            AuditEntry(
                action=AuditAction.SESSION_REVOKED,
                actor_id=user.id,
                actor_label=user.display_name,
                target_type="user",
                target_id=str(user.id),
                metadata={"scope": "others", "count": len(rows)},
                request=request,
            )
        )
    return len(rows)


def update_user_profile(
    *,
    user: User,
    first_name: str | None = None,
    last_name: str | None = None,
    national_code: str | None = None,
    province: str | None = None,
    city: str | None = None,
) -> User:
    """به‌روزرسانی مشخصات پروفایل خیر همراه با رمزنگاری کد ملی و بررسی یکتایی آن."""
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        if first_name is not None:
            locked.first_name = first_name.strip()[:80]
        if last_name is not None:
            locked.last_name = last_name.strip()[:80]
        if province is not None:
            locked.province = province.strip()[:80]
        if city is not None:
            locked.city = city.strip()[:80]
        if national_code is not None:
            cleaned_nc = national_code.strip()
            if cleaned_nc:
                valid_nc = validate_iranian_national_code(cleaned_nc)
                idx = blind_index(valid_nc, namespace="identity.national_code")
                if User.objects.filter(national_code_index=idx).exclude(pk=locked.pk).exists():
                    raise ConflictError(
                        "این کد ملی پیش‌تر برای حساب دیگری ثبت شده است.",
                        code="duplicate_national_code",
                    )
                locked.set_national_code(valid_nc)
            else:
                locked.set_national_code("")
        locked.save()
    return locked


# ── تأیید دومرحله‌ای کارکنان (TOTP + Recovery Codes + Step-Up) ──────────────


def _mfa_lockout_key(user: User) -> str:
    return f"mfa:fail:{user.pk}"


def _guard_mfa_lockout(user: User) -> None:
    failures = int(cache.get(_mfa_lockout_key(user)) or 0)
    if failures >= MFA_MAX_FAILURES:
        raise RateLimitedError(
            "به دلیل تلاش‌های ناموفق متوالی، تأیید دومرحله‌ای به مدت ۱۵ دقیقه قفل شد.",
            code="mfa_locked",
            extensions={"retry_after": MFA_LOCKOUT_SECONDS},
        )


def _record_mfa_failure(user: User, request: HttpRequest) -> None:
    key = _mfa_lockout_key(user)
    if not cache.add(key, 1, timeout=MFA_LOCKOUT_SECONDS):
        try:
            count = int(cache.incr(key))
        except ValueError:  # pragma: no cover
            cache.set(key, 1, timeout=MFA_LOCKOUT_SECONDS)
            count = 1
    else:
        count = 1
    if count >= MFA_MAX_FAILURES:
        AuthRiskSignal.objects.create(
            user=user,
            signal_type=AuthRiskType.MFA_LOCKOUT,
            ip_address=client_ip(request) or None,
            phone_masked=user.masked_phone,
            metadata={"failures": count},
        )
    record_audit(
        AuditEntry(
            action=AuditAction.MFA_FAILED,
            outcome=AuditOutcome.FAILURE,
            actor_id=user.id,
            actor_label=user.display_name,
            target_type="user",
            target_id=str(user.id),
            request=request,
        )
    )


def begin_staff_totp_setup(*, user: User) -> dict[str, str]:
    """شروع راه‌اندازی دستگاه TOTP کارمند و برگرداندن راز، URI و تصویر QR برداری."""
    if not user.is_staff_member:
        raise PermissionDeniedError("تأیید دومرحله‌ای سازمانی مخصوص کارکنان است.")
    existing = StaffTotpDevice.objects.filter(user=user, confirmed_at__isnull=False).first()
    if existing is not None:
        raise ConflictError(
            "دستگاه تأیید دومرحله‌ای شما قبلاً فعال شده است.",
            code="mfa_already_enrolled",
        )
    secret = totp.generate_totp_secret()
    StaffTotpDevice.objects.update_or_create(
        user=user,
        defaults={"secret_encrypted": encrypt_value(secret), "confirmed_at": None},
    )
    uri = totp.build_otpauth_uri(secret_b32=secret, account_label=user.phone)
    return {
        "secret": secret,
        "otpauth_uri": uri,
        "qr_svg": totp.render_qr_svg(uri),
    }


def _generate_recovery_codes(user: User) -> list[str]:
    StaffRecoveryCode.all_objects.get_queryset().filter(user=user).hard_delete()
    codes: list[str] = []
    rows: list[StaffRecoveryCode] = []
    for _ in range(RECOVERY_COUNT):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(10))
        formatted = f"{raw[:5]}-{raw[5:]}"
        codes.append(formatted)
        rows.append(
            StaffRecoveryCode(
                user=user,
                code_hash=blind_index(raw, namespace=RECOVERY_CODE_NAMESPACE),
            )
        )
    StaffRecoveryCode.objects.bulk_create(rows)
    return codes


def confirm_staff_totp_setup(
    *, user: User, session_obj: UserSession | None, code: str, request: HttpRequest
) -> list[str]:
    """تأیید اولیهٔ دستگاه TOTP، ارتقای نشست جاری و صدور ۱۰ کد بازیابی یک‌بارمصرف."""
    if not user.is_staff_member:
        raise PermissionDeniedError("دسترسی غیرمجاز.")
    _guard_mfa_lockout(user)
    device = StaffTotpDevice.objects.filter(user=user).first()
    if device is None:
        raise ConflictError("ابتدا مرحلهٔ setup را فراخوانی کنید.", code="mfa_setup_missing")
    if device.confirmed_at is not None:
        raise ConflictError("دستگاه قبلاً تأیید شده است.", code="mfa_already_enrolled")

    secret = decrypt_value(device.secret_encrypted)
    if not totp.verify_totp(secret, normalize_digits(code)):
        _record_mfa_failure(user, request)
        raise DomainValidationError(
            "کد ۶ رقمی اپلیکیشن احراز هویت صحیح نیست.",
            code="invalid_mfa_code",
            errors={"code": ["کد ۶ رقمی صحیح را وارد کنید."]},
        )

    now = timezone.now()
    with transaction.atomic():
        device.confirmed_at = now
        device.save(update_fields=["confirmed_at", "updated_at"])
        recovery_codes = _generate_recovery_codes(user)
        if session_obj is not None:
            session_obj.mfa_verified_at = now
            session_obj.mfa_method = "totp"
            session_obj.save(update_fields=["mfa_verified_at", "mfa_method", "updated_at"])
        cache.delete(_mfa_lockout_key(user))
        record_audit(
            AuditEntry(
                action=AuditAction.MFA_ENROLLED,
                actor_id=user.id,
                actor_label=user.display_name,
                target_type="user",
                target_id=str(user.id),
                request=request,
            )
        )
    return recovery_codes


def verify_staff_mfa(
    *, user: User, session_obj: UserSession | None, code: str, request: HttpRequest
) -> UserSession:
    """تأیید TOTP یا کد بازیابی روی نشست فعال کارمند (برای ورود و نیز Step-Up عملیات حساس)."""
    if not user.is_staff_member:
        raise PermissionDeniedError("دسترسی غیرمجاز.")
    if session_obj is None:
        raise AuthenticationRequiredError("نشست فعالی برای ثبت تأیید دومرحله‌ای یافت نشد.")

    _guard_mfa_lockout(user)
    device = StaffTotpDevice.objects.filter(user=user, confirmed_at__isnull=False).first()
    if device is None:
        raise ConflictError(
            "ابتدا باید تأیید دومرحله‌ای را راه‌اندازی کنید.",
            code="mfa_not_enrolled",
        )

    cleaned = normalize_digits(code or "").strip().upper()
    alnum = "".join(ch for ch in cleaned if ch.isalnum())
    method = ""

    secret = decrypt_value(device.secret_encrypted)
    if totp.verify_totp(secret, cleaned):
        method = "totp"
    elif len(alnum) == 10:
        digest = blind_index(alnum, namespace=RECOVERY_CODE_NAMESPACE)
        with transaction.atomic():
            rec = (
                StaffRecoveryCode.objects.select_for_update()
                .filter(user=user, code_hash=digest, used_at__isnull=True)
                .first()
            )
            if rec is not None:
                rec.used_at = timezone.now()
                rec.save(update_fields=["used_at", "updated_at"])
                method = "recovery"

    if not method:
        _record_mfa_failure(user, request)
        raise DomainValidationError(
            "کد تأیید دومرحله‌ای یا کد بازیابی نامعتبر است.",
            code="invalid_mfa_code",
            errors={"code": ["کد واردشده صحیح نیست."]},
        )

    now = timezone.now()
    with transaction.atomic():
        session_obj.mfa_verified_at = now
        session_obj.mfa_method = method
        if hasattr(request, "session") and request.session.session_key:
            request.session.cycle_key()
            request.session["user_session_id"] = str(session_obj.id)
            request.session.save()
            session_obj.session_key = request.session.session_key or ""
        session_obj.save(
            update_fields=["mfa_verified_at", "mfa_method", "session_key", "updated_at"]
        )
        cache.delete(_mfa_lockout_key(user))
        record_audit(
            AuditEntry(
                action=AuditAction.MFA_VERIFIED,
                actor_id=user.id,
                actor_label=user.display_name,
                target_type="session",
                target_id=str(session_obj.id),
                metadata={"method": method},
                request=request,
            )
        )
    return session_obj


def change_user_role(
    *,
    actor: User,
    target_user_id: str,
    new_role: str,
    reason: str,
    request: HttpRequest,
) -> User:
    """تغییر نقش کاربر توسط مدیر ارشد همراه با ثبت دلیل اجباری و حسابرسی."""
    if not (actor.is_superuser or actor.role == UserRole.SUPER_ADMIN):
        raise PermissionDeniedError("فقط مدیر ارشد مجاز به تغییر نقش کاربران است.")
    if new_role not in UserRole.values:
        raise DomainValidationError(
            "نقش انتخاب‌شده معتبر نیست.",
            errors={"role": ["نقش معتبر انتخاب کنید."]},
        )
    cleaned_reason = reason.strip()
    if len(cleaned_reason) < 5:
        raise DomainValidationError(
            "ثبت دلیل برای تغییر نقش کاربری الزامی است.",
            errors={"reason": ["دلیل تغییر نقش را وارد کنید."]},
        )

    with transaction.atomic():
        target = User.objects.select_for_update().filter(pk=target_user_id).first()
        if target is None:
            raise NotFoundError("کاربر مورد نظر یافت نشد.")
        old_role = target.role
        target.role = new_role
        target.is_staff = new_role in {
            UserRole.OPERATOR,
            UserRole.FINANCE_MANAGER,
            UserRole.SUPER_ADMIN,
        }
        target.save(update_fields=["role", "is_staff", "updated_at"])
        record_audit(
            AuditEntry(
                action=AuditAction.ROLE_CHANGED,
                actor_id=actor.id,
                actor_label=actor.display_name,
                target_type="user",
                target_id=str(target.id),
                reason=cleaned_reason,
                metadata={"old_role": old_role, "new_role": new_role},
                request=request,
            )
        )
    return target


def reveal_donor_phone(
    *, actor: User, target_user_id: str, reason: str, request: HttpRequest
) -> str:
    """نمایش شماره موبایل کامل خیر برای کارمند مجاز فقط با تأیید تازه و ثبت هدف ممیزی."""
    cleaned_reason = reason.strip()
    if len(cleaned_reason) < 5:
        raise DomainValidationError(
            "ذکر دلیل عملیاتی (حداقل ۵ نویسه) برای مشاهدهٔ شمارهٔ کامل خیر الزامی است.",
            code="reason_required",
            errors={"reason": ["علت نیاز به تماس مستقیم را ثبت کنید."]},
        )
    target = User.objects.filter(pk=target_user_id).first()
    if target is None:
        raise NotFoundError("کاربر یافت نشد.")
    record_audit(
        AuditEntry(
            action=AuditAction.PII_PHONE_REVEALED,
            actor_id=actor.id,
            actor_label=actor.display_name,
            target_type="user",
            target_id=str(target.id),
            reason=cleaned_reason,
            request=request,
        )
    )
    return target.phone


def review_auth_risk_signal(
    *, actor: User, signal_id: str, new_status: str, note: str
) -> AuthRiskSignal:
    """بررسی و تعیین وضعیت سیگنال ریسک هویتی توسط مدیر."""
    if new_status not in {RiskReviewStatus.REVIEWED, RiskReviewStatus.DISMISSED}:
        raise DomainValidationError(
            "وضعیت بررسی معتبر نیست.",
            errors={"status": ["مقدار reviewed یا dismissed ارسال کنید."]},
        )
    with transaction.atomic():
        sig = AuthRiskSignal.objects.select_for_update().filter(pk=signal_id).first()
        if sig is None:
            raise NotFoundError("سیگنال ریسک یافت نشد.")
        sig.status = new_status
        sig.reviewed_by = actor
        sig.reviewed_at = timezone.now()
        sig.review_note = note.strip()[:400]
        sig.save(
            update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "updated_at"]
        )
    return sig
