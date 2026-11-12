"""پیاده‌سازی استاندارد RFC 6238 TOTP و تولید QR SVG برای تأیید دومرحله‌ای کارکنان."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import os
import struct
import time
from urllib.parse import quote

import segno

TOTP_DIGITS = 6
TOTP_STEP_SECONDS = 30


def generate_totp_secret() -> str:
    """تولید راز تصادفی ۱۶۰ بیتی در قالب Base32 بدون پدینگ."""
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    padded = secret_b32.upper() + "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (
        10**TOTP_DIGITS
    )
    return f"{code_int:0{TOTP_DIGITS}d}"


def current_totp(secret_b32: str, *, at_timestamp: float | None = None) -> str:
    """محاسبهٔ کد ۶ رقمی TOTP برای لحظهٔ فعلی (یا زمان داده‌شده)."""
    ts = time.time() if at_timestamp is None else at_timestamp
    counter = int(ts) // TOTP_STEP_SECONDS
    return _hotp(secret_b32, counter)


def verify_totp(
    secret_b32: str, candidate: str, *, window: int = 1, at_timestamp: float | None = None
) -> bool:
    """بررسی کد ۶ رقمی با تلرانس یک گام زمانی (۳۰ ثانیه) در برابر اختلاف ساعت گوشی."""
    cleaned = (candidate or "").strip()
    if len(cleaned) != TOTP_DIGITS or not cleaned.isdigit():
        return False
    ts = time.time() if at_timestamp is None else at_timestamp
    base_counter = int(ts) // TOTP_STEP_SECONDS
    for delta in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret_b32, base_counter + delta), cleaned):
            return True
    return False


def build_otpauth_uri(*, secret_b32: str, account_label: str, issuer: str = "Crowdfunding") -> str:
    """ساخت نشانی استاندارد ``otpauth://`` سازگار با Google Authenticator و Authy."""
    safe_issuer = quote(issuer)
    safe_label = quote(f"{issuer}:{account_label}")
    return (
        f"otpauth://totp/{safe_label}?secret={secret_b32}"
        f"&issuer={safe_issuer}&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_STEP_SECONDS}"
    )


def render_qr_svg(data: str) -> str:
    """تولید تصویر برداری QR در قالب رشتهٔ SVG بدون وابستگی به کتابخانه‌های تصویری بومی."""
    qr = segno.make(data, micro=False)
    buf = io.BytesIO()
    qr.save(buf, kind="svg", xmldecl=False, scale=4, border=2)
    return buf.getvalue().decode("utf-8")
