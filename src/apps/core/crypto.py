"""رمزنگاری میدانی AES-256-GCM، ایندکس کور HMAC-SHA256 و پوشاندن داده‌های حساس (PII).

این ماژول سه تضمین امنیتی هم‌زمان ارائه می‌دهد:
    ۱. محرمانگی و اصالت در سکون (At-Rest Authenticated Encryption) با AES-GCM نسخه‌دار
       (قالب ``v1:<nonce_b64>:<ciphertext_b64>``) جهت پشتیبانی از چرخش کلید بدون توقف.
    ۲. یکتایی و قابلیت جست‌وجو بدون رمزگشایی از طریق ایندکس کور فضا‌بندی‌شده (HMAC-SHA256).
    ۳. پوشاندن استاندارد شماره موبایل، کد ملی و شبای بانکی در تمامی خروجی‌های عادی.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

KEY_VERSION = "v1"
_KEY_BYTES = 32
_NONCE_BYTES = 12
_TOKEN_PARTS = 3


def _encryption_key() -> bytes:
    """استخراج کلید ۳۲ بایتی AES-256-GCM از تنظیمات محیطی."""
    configured = str(getattr(settings, "FIELD_ENCRYPTION_KEY", "") or "")
    if not configured:
        msg = "متغیر FIELD_ENCRYPTION_KEY تنظیم نشده است؛ رمزنگاری فیلدهای حساس ممکن نیست."
        raise ImproperlyConfigured(msg)
    try:
        decoded = base64.b64decode(configured, validate=True)
    except (binascii.Error, ValueError):
        decoded = b""
    if len(decoded) == _KEY_BYTES:
        return decoded
    return hashlib.sha256(configured.encode("utf-8")).digest()


def _hash_key() -> bytes:
    """استخراج کلید HMAC برای ایندکس کور و امضاهای داخلی."""
    configured = str(getattr(settings, "FIELD_HASH_KEY", "") or "")
    if not configured:
        configured = str(settings.SECRET_KEY)
    return hashlib.sha256(configured.encode("utf-8")).digest()


def encrypt_value(plaintext: str | None) -> str:
    """رمزنگاری رشتهٔ حساس با AES-256-GCM؛ مقدار خالی دست‌نخورده می‌ماند."""
    if not plaintext:
        return ""
    aead = AESGCM(_encryption_key())
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = aead.encrypt(nonce, plaintext.encode("utf-8"), None)
    nonce_b64 = base64.b64encode(nonce).decode("ascii")
    body_b64 = base64.b64encode(ciphertext).decode("ascii")
    return f"{KEY_VERSION}:{nonce_b64}:{body_b64}"


def is_encrypted(value: str | None) -> bool:
    """تشخیص این‌که آیا رشته در قالب رمزنگاری‌شدهٔ این سامانه قرار دارد یا خیر."""
    if not value:
        return False
    parts = value.split(":")
    return len(parts) == _TOKEN_PARTS and parts[0] == KEY_VERSION


def decrypt_value(token: str | None, *, default: str = "") -> str:
    """رمزگشایی امن مقدار رمزنگاری‌شده؛ دستکاری یا کلید نامعتبر لاگ شده و default برمی‌گرداند."""
    if not token:
        return default
    if not is_encrypted(token):
        return token
    _, nonce_b64, body_b64 = token.split(":", 2)
    try:
        nonce = base64.b64decode(nonce_b64)
        body = base64.b64decode(body_b64)
        aead = AESGCM(_encryption_key())
        return aead.decrypt(nonce, body, None).decode("utf-8")
    except Exception:
        logger.exception("field_decryption_failed")
        return default


def blind_index(value: str | None, *, namespace: str = "default") -> str:
    """تولید ایندکس کور HMAC-SHA256 با جداسازی فضای نام برای جلوگیری از تطبیق بین‌جدولی."""
    if not value:
        return ""
    normalized = value.strip()
    if not normalized:
        return ""
    message = f"{namespace}:{normalized}".encode()
    return hmac.new(_hash_key(), message, hashlib.sha256).hexdigest()


def sign_payload(canonical_text: str, *, namespace: str = "signature") -> str:
    """امضای HMAC-SHA256 متعارف برای گواهی‌ها، رسیدها و لنگرهای حسابرسی."""
    message = f"{namespace}|{canonical_text}".encode()
    return hmac.new(_hash_key(), message, hashlib.sha256).hexdigest()


def verify_signature(canonical_text: str, signature: str, *, namespace: str = "signature") -> bool:
    """بررسی زمان‌ثابت امضای HMAC-SHA256 در برابر حملات زمان‌سنجی."""
    expected = sign_payload(canonical_text, namespace=namespace)
    return hmac.compare_digest(expected, signature or "")


def mask_phone(phone: str | None) -> str:
    """پوشاندن شماره تلفن برای نمایش امن به اپراتور و گزارش‌های پیش‌فرض (مثلاً ``0912***4567``)."""
    if not phone:
        return ""
    cleaned = phone.strip()
    if len(cleaned) < 7:
        return "***"
    return f"{cleaned[:4]}***{cleaned[-4:]}"


def mask_national_code(code: str | None) -> str:
    """نمایش صرفاً ۴ رقم پایانی کد ملی."""
    if not code:
        return ""
    cleaned = code.strip()
    if len(cleaned) <= 4:
        return "******"
    return f"******{cleaned[-4:]}"


def mask_iban(iban: str | None) -> str:
    """پوشاندن شماره شبا با حفظ پیشوند IR و ۴ رقم پایانی."""
    if not iban:
        return ""
    cleaned = iban.replace(" ", "").upper()
    if len(cleaned) <= 8:
        return "IR********************"
    return f"{cleaned[:4]}{'*' * (len(cleaned) - 8)}{cleaned[-4:]}"
