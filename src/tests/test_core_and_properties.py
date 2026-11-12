"""آزمون‌های هستهٔ مشترک و آزمون‌های خاصیت‌محور Hypothesis (پول ریال/تومان، جلالی، رمزنگاری، RFC 9457)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from hypothesis import given, settings as hyp_settings, strategies as st
import pytest
from rest_framework.test import APIClient

from apps.core.cache import bump_epoch, get_epoch, get_or_set_versioned
from apps.core.crypto import (
    blind_index,
    decrypt_value,
    encrypt_value,
    mask_iban,
    mask_national_code,
    mask_phone,
    sign_payload,
    verify_signature,
)
from apps.core.errors import ValidationError as DomainValidationError
from apps.core.jalali import (
    format_jalali_date,
    format_jalali_datetime,
    normalize_digits,
    to_persian_digits,
)
from apps.core.logging import redact_value
from apps.core.money import MoneyPair, money_fields, rial_to_toman, toman_to_rial
from apps.core.netpin import assert_safe_endpoint
from apps.core.policy import get_policy, is_feature_enabled, set_policy_value
from apps.identity.models import User
from apps.identity.validators import (
    compute_iban_check_digits,
    normalize_phone,
    validate_iranian_iban,
    validate_iranian_national_code,
)
from tests.conftest import issue_client_for_user


@given(toman=st.integers(min_value=0, max_value=10**14))
@hyp_settings(max_examples=80, deadline=None)
def test_property_toman_rial_exact_integer_roundtrip(toman: int) -> None:
    """تبدیل تومان -> ریال -> تومان برای تمام اعداد صحیح نامنفی دقیقاً بی‌اتلاف و بدون ممیز شناور است."""
    rial = toman_to_rial(toman)
    assert isinstance(rial, int)
    assert rial == toman * 10
    assert rial_to_toman(rial) == toman
    pair = MoneyPair(rial=rial)
    assert pair.rial == rial
    assert pair.toman == toman
    fields = money_fields("amount", rial)
    assert fields == {"amount_rial": rial, "amount_toman": toman}


@given(raw_num=st.integers(min_value=0, max_value=999_999_999_999))
@hyp_settings(max_examples=60, deadline=None)
def test_property_persian_digit_conversion_roundtrip(raw_num: int) -> None:
    """تبدیل ارقام لاتین به فارسی و نرمال‌سازی مجدد همیشه رشتهٔ عددی اصلی را بازتولید می‌کند."""
    ascii_str = str(raw_num)
    persian_str = to_persian_digits(ascii_str)
    assert normalize_digits(persian_str) == ascii_str


@given(days_offset=st.integers(min_value=0, max_value=20_000))
@hyp_settings(max_examples=80, deadline=None)
def test_property_jalali_formatting_produces_valid_calendar_bounds(days_offset: int) -> None:
    """تبدیل تاریخ میلادی به شمسی برای بازهٔ ۵۵ ساله همواره سال/ماه/روز معتبر تولید می‌کند."""
    base = date(1995, 1, 1).fromordinal(date(1995, 1, 1).toordinal() + days_offset)
    j_str = format_jalali_date(base)
    parts = j_str.split("-")
    assert len(parts) == 3
    jy, jm, jd = int(parts[0]), int(parts[1]), int(parts[2])
    assert 1370 <= jy <= 1440
    assert 1 <= jm <= 12
    max_day = 31 if jm <= 6 else 30
    assert 1 <= jd <= max_day


def test_jalali_known_nowruz_and_leap_dates() -> None:
    """صحت دقیق تاریخ‌های مرجع نوروز و سال کبیسه شمسی."""
    assert format_jalali_date(date(2026, 3, 21)) == "1405-01-01"
    dt = datetime(2026, 3, 21, 14, 30, tzinfo=ZoneInfo("Asia/Tehran"))
    assert format_jalali_datetime(dt).startswith("1405-01-01")


@given(secret_text=st.text(min_size=1, max_size=120))
@hyp_settings(max_examples=40, deadline=None)
def test_property_fernet_encryption_and_hmac_signature(secret_text: str) -> None:
    """رمزنگاری Fernet و امضای HMAC روی هر متن یونیکد رفت‌وبرگشت دقیق دارند و در برابر دستکاری مقاوم‌اند."""
    cipher = encrypt_value(secret_text)
    assert cipher != secret_text
    assert decrypt_value(cipher) == secret_text

    sig = sign_payload(secret_text, namespace="test.sig")
    assert verify_signature(secret_text, sig, namespace="test.sig") is True
    assert verify_signature(secret_text + "!", sig, namespace="test.sig") is False
    assert verify_signature(secret_text, sig, namespace="other.ns") is False


def test_blind_index_masking_and_pii_log_redaction() -> None:
    """ایندکس کور HMAC، پوشاندن داده‌های حساس و حذف PII در لاگ ساختاریافته."""
    idx_a = blind_index("0012345678", namespace="nc")
    idx_b = blind_index("0012345678", namespace="nc")
    idx_other = blind_index("0012345678", namespace="iban")
    assert idx_a == idx_b
    assert idx_a != idx_other

    assert "***" in mask_phone("09121234567")
    assert "***" in mask_national_code("0012345678")
    assert "*" in mask_iban("IR060170000000001122334455")

    redacted = redact_value("phone", "09121234567")
    assert "1234" not in str(redacted)
    nested = redact_value("payload", {"otp_code": "54321", "safe_title": "سلام"})
    assert nested["otp_code"] == "[REDACTED]"
    assert nested["safe_title"] == "سلام"


@given(bban=st.from_regex(r"^[0-9]{22}$", fullmatch=True))
@hyp_settings(max_examples=40, deadline=None)
def test_property_iranian_iban_iso7064_mod97(bban: str) -> None:
    """هر ۲۲ رقم پایه با ارقام کنترلی محاسبه‌شده یک شبای معتبر ایران تولید می‌کند و تغییر ۱ رقم رد می‌شود."""
    chk = compute_iban_check_digits(bban)
    iban = f"IR{chk}{bban}"
    assert validate_iranian_iban(iban) == iban

    flipped_last = "0" if bban[-1] != "0" else "1"
    corrupted = f"IR{chk}{bban[:-1]}{flipped_last}"
    with pytest.raises((ValueError, DomainValidationError)):
        validate_iranian_iban(corrupted)


def test_iranian_phone_and_national_code_validators() -> None:
    """اعتبارسنجی شماره موبایل ایران با ارقام فارسی/پیش‌شماره +98 و کد ملی ده رقمی."""
    assert normalize_phone("۰۹۱۲۱۲۳۴۵۶۷") == "09121234567"
    assert normalize_phone("+989121234567") == "09121234567"
    assert normalize_phone("00989121234567") == "09121234567"

    # ساخت کد ملی معتبر با فرمول ده رقمی
    digits = [0, 0, 1, 3, 5, 2, 4, 6, 8]
    s = sum(digits[i] * (10 - i) for i in range(9))
    rem = s % 11
    ctrl = rem if rem < 2 else 11 - rem
    valid_nc = "".join(str(d) for d in [*digits, ctrl])
    assert validate_iranian_national_code(valid_nc) == valid_nc


def test_ssrf_guard_blocks_private_ips_and_http_in_production() -> None:
    """در محیط تولید پروتکل HTTP، localhost و IPهای خصوصی مسدود می‌شوند."""
    with override_settings(DEBUG=False, TESTING=False):
        assert assert_safe_endpoint("https://payment.zarinpal.com/pg/v4/request.json")
        with pytest.raises(ImproperlyConfigured):
            assert_safe_endpoint("http://payment.zarinpal.com/pg/v4/request.json")
        with pytest.raises(ImproperlyConfigured):
            assert_safe_endpoint("https://127.0.0.1/internal")
        with pytest.raises(ImproperlyConfigured):
            assert_safe_endpoint("https://169.254.169.254/latest/meta-data")
        with pytest.raises(ImproperlyConfigured):
            assert_safe_endpoint("https://localhost/api")


@pytest.mark.django_db
def test_rfc9457_problem_details_etag_epoch_and_policy_api(
    api_client: APIClient,
    seeded_policies: None,
    super_admin_user: User,
) -> None:
    """پاسخ خطای RFC 9457، هدرهای امنیتی، کش ETag/304، سلامت سرویس و مدیریت Policy-as-Data."""
    del seeded_policies
    # ۱. سلامت، آمادگی و متریک‌ها
    live = api_client.get("/api/v1/health/live")
    assert live.status_code == 200
    assert live.json()["status"] == "alive"

    ready = api_client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"

    metrics = api_client.get("/metrics")
    assert metrics.status_code == 200
    assert "crowdfunding_http_request_duration_seconds" in metrics.content.decode("utf-8")

    # ۲. متا و پشتیبانی از ETag / If-None-Match -> 304 Not Modified
    meta_resp = api_client.get("/api/v1/meta", HTTP_X_REQUEST_ID="req-test-12345")
    assert meta_resp.status_code == 200
    assert meta_resp["X-Request-ID"] == "req-test-12345"
    assert meta_resp["X-Content-Type-Options"] == "nosniff"
    etag = meta_resp["ETag"]
    assert etag

    not_mod = api_client.get("/api/v1/meta", HTTP_IF_NONE_MATCH=etag)
    assert not_mod.status_code == 304

    # ۳. خطای ۴۰۴ استاندارد RFC 9457
    err_404 = api_client.get("/api/v1/non-existent-route")
    assert err_404.status_code == 404
    assert err_404["Content-Type"].startswith("application/problem+json")
    body = err_404.json()
    for required_key in ("type", "title", "status", "detail", "code", "instance", "trace_id"):
        assert required_key in body
    assert body["status"] == 404

    # ۴. ابطال کش مبتنی بر Epoch
    calls = {"n": 0}

    def _produce() -> dict[str, int]:
        calls["n"] += 1
        return {"v": calls["n"]}

    v1 = get_or_set_versioned("campaigns", "global", "home", _produce)
    v2 = get_or_set_versioned("campaigns", "global", "home", _produce)
    assert v1 == v2 == {"v": 1}
    old_ep = get_epoch("campaigns")
    new_ep = bump_epoch("campaigns")
    assert new_ep > old_ep
    v3 = get_or_set_versioned("campaigns", "global", "home", _produce)
    assert v3 == {"v": 2}

    # ۵. تغییر پویا در Policy-as-Data توسط مدیر ارشد با MFA تازه و ثبت تاریخچه
    admin_client, _ = issue_client_for_user(super_admin_user, mfa_fresh=True)
    pol_list = admin_client.get("/api/v1/admin/policies")
    assert pol_list.status_code == 200
    assert "no-store" in pol_list["Cache-Control"]

    upd = admin_client.post(
        "/api/v1/admin/policies/share.hold_ttl_minutes",
        data={"value": 20, "reason": "افزایش مهلت پرداخت در ایام پرترافیک"},
        format="json",
    )
    assert upd.status_code == 200
    assert get_policy("share.hold_ttl_minutes") == 20

    set_policy_value(
        key="feature.matching_grants",
        value=False,
        reason="آزمون غیرفعال‌سازی موقت ویژگی",
        actor_id=str(super_admin_user.id),
    )
    assert is_feature_enabled("feature.matching_grants") is False
