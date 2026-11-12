"""تنظیمات محیط اجرای تست‌های خودکار (Pytest بر روی MariaDB واقعی)."""

from __future__ import annotations

from config.settings.base import *

DEBUG = False
TESTING = True
EXPOSE_DEV_OTP_CODE = True
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "crowdfunding-test-cache",
    }
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {
        "anon_public": "1000/min",
        "otp_request": "200/min",
        "otp_verify": "200/min",
        "mfa_verify": "200/min",
        "checkout": "500/min",
    },
}
