"""تنظیمات سخت‌گیرانهٔ محیط عملیاتی تولید (Production — بهینه‌شده برای هاست سی‌پنل نایترو و CloudLinux Passenger)."""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

from config.settings.base import *

DEBUG = False
ENVIRONMENT = "production"
EXPOSE_DEV_OTP_CODE = False

if SECRET_KEY.startswith("dev-only-insecure") or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured(
        "در محیط تولید تنظیم متغیر محیطی DJANGO_SECRET_KEY با طول حداقل ۵۰ کاراکتر الزامی است."
    )

for _required_secret in ("FIELD_ENCRYPTION_KEY", "PII_BLIND_INDEX_KEY", "AUDIT_ANCHOR_HMAC_KEY"):
    if not os.environ.get(_required_secret):
        raise ImproperlyConfigured(
            f"در محیط تولید تنظیم متغیر رمزنگاری مستقل {_required_secret} الزامی است."
        )

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

SECURE_HSTS_SECONDS = 63_072_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
