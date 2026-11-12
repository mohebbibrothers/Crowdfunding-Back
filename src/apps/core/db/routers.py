"""مسیریاب پایگاه‌داده برای جداسازی تراکنش‌های کش از تراکنش‌های دامنه‌ای.

روی هاست اشتراکی Nitro cPanel (بدون Redis)، شمارنده‌های قفل MFA، سقف نرخ OTP و
نسخهٔ کش Epoch درون جدول ``django_cache`` نگهداری می‌شوند. اگر این جدول از همان
اتصال ``default`` استفاده کند، هنگام برگشت (Rollback) تراکنش درخواست، افزایش
شمارندهٔ تلاش ناموفق هم برمی‌گردد! با هدایت جدول کش به اتصال مجزای ``cache`` در
حالت autocommit، رفتار کش دقیقاً هم‌ارز Redis باقی می‌ماند.
"""

from __future__ import annotations

from typing import Any

CACHE_ALIAS = "cache"
CACHE_APP_LABEL = "django_cache"


class CacheRouter:
    """هدایت عملیات خواندن و نوشتن جدول کش به اتصال مستقل ``cache``."""

    def db_for_read(self, model: type[Any], **hints: Any) -> str | None:
        """انتخاب اتصال کش برای خواندن مدل جدول کش."""
        del hints
        if model._meta.app_label == CACHE_APP_LABEL and self._has_cache_db():
            return CACHE_ALIAS
        return None

    def db_for_write(self, model: type[Any], **hints: Any) -> str | None:
        """انتخاب اتصال کش برای نوشتن مدل جدول کش."""
        del hints
        if model._meta.app_label == CACHE_APP_LABEL and self._has_cache_db():
            return CACHE_ALIAS
        return None

    def allow_migrate(
        self, db: str, app_label: str, model_name: str | None = None, **hints: Any
    ) -> bool | None:
        """جلوگیری از ساخت جداول دامنه روی اتصال فرعی کش."""
        del model_name, hints
        if app_label == CACHE_APP_LABEL:
            return True
        if db == CACHE_ALIAS:
            return False
        return None

    @staticmethod
    def _has_cache_db() -> bool:
        from django.conf import settings

        return CACHE_ALIAS in getattr(settings, "DATABASES", {})
