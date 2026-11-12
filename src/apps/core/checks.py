"""سیستم‌چک‌های امنیتی استقرار جنگو برای جلوگیری از بالا آمدن پیکربندی ناامن در تولید."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def check_production_hygiene(app_configs: Any, **kwargs: Any) -> list[Error]:
    """تضمین عدم استفاده از درگاه Sandbox، کلیدهای ضعیف یا CORS بدشکل در محیط تولید."""
    del app_configs, kwargs
    errors: list[Error] = []
    if getattr(settings, "ENVIRONMENT", "development") != "production":
        return errors

    if (
        getattr(
            settings,
            "PAYMENT_DEFAULT_GATEWAY",
            getattr(settings, "PAYMENT_PROVIDER", "sandbox"),
        )
        == "sandbox"
    ):
        errors.append(
            Error(
                "استفاده از درگاه پرداخت ساختگی (sandbox) در محیط تولید ممنوع است.",
                id="crowdfunding.E001",
            )
        )
    enc_key = str(getattr(settings, "FIELD_ENCRYPTION_KEY", "") or "")
    if len(enc_key) < 32:
        errors.append(
            Error(
                "کلید FIELD_ENCRYPTION_KEY در محیط تولید باید حداقل ۳۲ نویسه باشد.",
                id="crowdfunding.E002",
            )
        )
    for origin in getattr(settings, "CORS_ALLOWED_ORIGINS", []):
        if origin.endswith("/") or "://" not in origin:
            errors.append(
                Error(
                    f"مبدأ نامعتبر در CORS_ALLOWED_ORIGINS: {origin}",
                    id="crowdfunding.E003",
                )
            )
    return errors
