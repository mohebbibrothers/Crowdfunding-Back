"""تنظیمات محیط توسعهٔ محلی (Development)."""

from __future__ import annotations

from config.settings.base import *

DEBUG = True
ALLOWED_HOSTS = ["*"]
EXPOSE_DEV_OTP_CODE = True
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
