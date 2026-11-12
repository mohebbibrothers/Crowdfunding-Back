"""مدل‌های خیریه/نهاد نیکوکاری و قلک عام خیریه (مشارکت آزاد بدون محدودیت سهم)."""

from __future__ import annotations

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.models import BaseModel


def default_jar_suggested_amounts() -> list[int]:
    """مبالغ پیشنهادی پیش‌فرض قلک عام به ریال (۵۰، ۱۰۰، ۵۰۰ هزار و ۱ میلیون تومان)."""
    return [500_000, 1_000_000, 5_000_000, 10_000_000]


class Benefactor(BaseModel):
    """خیریه، مؤسسه یا نهاد نیکوکاری تعریف‌شده توسط مدیر سامانه برای تعریف حرکت و تسویه."""

    name = models.CharField(max_length=180, verbose_name=_("نام خیریه / نهاد"))
    slug = models.SlugField(
        max_length=120, unique=True, allow_unicode=True, verbose_name=_("نامک یکتا")
    )
    registration_number = models.CharField(
        max_length=64, blank=True, default="", verbose_name=_("شماره ثبت مجوز")
    )
    national_identifier = models.CharField(
        max_length=32, blank=True, default="", verbose_name=_("شناسه ملی حقوقی")
    )
    province = models.CharField(
        max_length=80, blank=True, default="", db_index=True, verbose_name=_("استان")
    )
    city = models.CharField(max_length=80, blank=True, default="", verbose_name=_("شهر"))
    short_bio = models.CharField(
        max_length=320, blank=True, default="", verbose_name=_("معرفی کوتاه")
    )
    description = models.TextField(blank=True, default="", verbose_name=_("شرح کامل فعالیت‌ها"))
    logo_url = models.CharField(
        max_length=500, blank=True, default="", verbose_name=_("نشانی لوگو")
    )
    cover_url = models.CharField(
        max_length=500, blank=True, default="", verbose_name=_("نشانی تصویر کاور")
    )
    website_url = models.CharField(
        max_length=300, blank=True, default="", verbose_name=_("وب‌سایت رسمی")
    )
    contact_phone = models.CharField(
        max_length=32, blank=True, default="", verbose_name=_("تلفن تماس")
    )
    iban = models.CharField(
        max_length=26,
        blank=True,
        default="",
        help_text=_("شماره شبای رسمی ۲۶ کاراکتری حساب تسویهٔ خیریه (IR...)."),
        verbose_name=_("شماره شبا (IBAN)"),
    )
    bank_holder_name = models.CharField(
        max_length=180, blank=True, default="", verbose_name=_("نام صاحب حساب بانکی")
    )
    is_verified = models.BooleanField(
        default=True, db_index=True, verbose_name=_("تأیید اصالت مدارک")
    )
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("فعال"))
    display_order = models.PositiveIntegerField(default=100, verbose_name=_("ترتیب نمایش"))

    # شمارنده‌های خوانشی اتمیک (به‌روزرسانی تراکنشی پس از پرداخت/تسویه)
    active_campaigns_count = models.PositiveIntegerField(
        default=0, verbose_name=_("تعداد حرکت‌های فعال")
    )
    completed_campaigns_count = models.PositiveIntegerField(
        default=0, verbose_name=_("تعداد حرکت‌های تکمیل‌شده")
    )
    total_raised_rial = models.BigIntegerField(default=0, verbose_name=_("مجموع جذب‌شده به ریال"))
    total_disbursed_rial = models.BigIntegerField(
        default=0, verbose_name=_("مجموع تسویه‌شده به ریال")
    )

    class Meta:
        verbose_name = _("خیریه / نهاد نیکوکاری")
        verbose_name_plural = _("خیریه‌ها و نهادهای نیکوکاری")
        ordering = ["display_order", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(total_raised_rial__gte=0) & Q(total_disbursed_rial__gte=0),
                name="benefactor_non_negative_totals_chk",
            ),
        ]

    def __str__(self) -> str:
        """نمایش نام خیریه."""
        return self.name


class CharityJar(BaseModel):
    """قلک عام خیریه برای مشارکت با مبلغ دلخواه خارج از ساختار سهم‌بندی حرکت‌های خاص."""

    benefactor = models.ForeignKey(
        Benefactor,
        on_delete=models.PROTECT,
        related_name="jars",
        verbose_name=_("خیریهٔ صاحب قلک"),
    )
    title = models.CharField(max_length=180, verbose_name=_("عنوان قلک"))
    slug = models.SlugField(
        max_length=120, unique=True, allow_unicode=True, verbose_name=_("نامک یکتا")
    )
    short_code = models.CharField(
        max_length=16, unique=True, db_index=True, verbose_name=_("کد پیوندک کوتاه")
    )
    description = models.TextField(blank=True, default="", verbose_name=_("توضیحات مصرف قلک"))
    suggested_amounts_rial = models.JSONField(
        default=default_jar_suggested_amounts,
        verbose_name=_("مبالغ پیشنهادی سریع (ریال)"),
    )
    min_amount_rial = models.BigIntegerField(
        default=100_000, verbose_name=_("حداقل مبلغ مجاز (ریال)")
    )
    max_amount_rial = models.BigIntegerField(
        default=5_000_000_000, verbose_name=_("حداکثر مبلغ مجاز در هر تراکنش (ریال)")
    )
    monthly_goal_rial = models.BigIntegerField(
        default=0, verbose_name=_("هدف انگیزشی ماهانه (ریال؛ صفر = بدون هدف)")
    )
    total_raised_rial = models.BigIntegerField(
        default=0, verbose_name=_("مجموع واریزی به قلک (ریال)")
    )
    donor_count = models.PositiveIntegerField(default=0, verbose_name=_("شمار مشارکت‌های موفق"))
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("فعال"))

    class Meta:
        verbose_name = _("قلک عام خیریه")
        verbose_name_plural = _("قلک‌های عام خیریه")
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(min_amount_rial__gte=10_000)
                    & Q(max_amount_rial__gte=models.F("min_amount_rial"))
                    & Q(monthly_goal_rial__gte=0)
                    & Q(total_raised_rial__gte=0)
                ),
                name="charity_jar_bounds_chk",
            ),
        ]

    def __str__(self) -> str:
        """نمایش عنوان قلک و نام خیریه."""
        return f"{self.title} ({self.benefactor.name})"
