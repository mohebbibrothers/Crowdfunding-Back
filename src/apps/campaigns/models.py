"""مدل‌های دسته‌بندی، حرکت خیرخواهانهٔ سهم‌محور، گالری، حامی مضاعف‌کننده و گزارش میدانی."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from apps.benefactors.models import Benefactor
from apps.campaigns.choices import (
    CampaignMediaKind,
    CampaignStatus,
    CampaignUrgency,
    ImpactMilestoneType,
)
from apps.core.models import BaseModel


class CampaignCategory(BaseModel):
    """دسته‌بندی موضوعی حرکت‌های خیرخواهانه (درمان، جهیزیه، آزادی زندانیان، مسکن و ...)."""

    title = models.CharField(max_length=120, verbose_name=_("عنوان دسته‌بندی"))
    slug = models.SlugField(
        max_length=80, unique=True, allow_unicode=True, verbose_name=_("نامک یکتا")
    )
    icon_name = models.CharField(max_length=64, blank=True, default="", verbose_name=_("نام آیکن"))
    description = models.CharField(
        max_length=300, blank=True, default="", verbose_name=_("توضیح کوتاه")
    )
    display_order = models.PositiveIntegerField(default=100, verbose_name=_("ترتیب نمایش"))
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("فعال"))

    class Meta:
        verbose_name = _("دسته‌بندی موضوعی حرکت")
        verbose_name_plural = _("دسته‌بندی‌های موضوعی حرکت‌ها")
        ordering = ["display_order", "title"]

    def __str__(self) -> str:
        """نمایش عنوان دسته‌بندی."""
        return self.title


class Campaign(BaseModel):
    """حرکت خیرخواهانهٔ سهم‌محور با تضمین اتمیک شمارنده‌ها و تغییرناپذیری مالی پس از اولین پرداخت."""

    benefactor = models.ForeignKey(
        Benefactor,
        on_delete=models.PROTECT,
        related_name="campaigns",
        verbose_name=_("خیریه / نهاد مجری"),
    )
    category = models.ForeignKey(
        CampaignCategory,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="campaigns",
        verbose_name=_("دسته‌بندی موضوعی"),
    )
    title = models.CharField(max_length=220, verbose_name=_("عنوان حرکت"))
    slug = models.SlugField(
        max_length=140, unique=True, allow_unicode=True, verbose_name=_("نامک یکتا")
    )
    short_code = models.CharField(
        max_length=16,
        unique=True,
        db_index=True,
        help_text=_("کد کوتاه پیوندک برای اشتراک‌گذاری سریع (مشابه پیوندک مددا)."),
        verbose_name=_("کد پیوندک کوتاه"),
    )
    subtitle = models.CharField(
        max_length=320, blank=True, default="", verbose_name=_("خلاصهٔ یک‌خطی")
    )
    why_and_what = models.TextField(
        blank=True,
        default="",
        help_text=_("روایت کامل چیستی، چرایی و نحوهٔ مصرف منابع حرکت."),
        verbose_name=_("چیستی و چرایی حرکت"),
    )
    cover_image_url = models.CharField(
        max_length=500, blank=True, default="", verbose_name=_("نشانی تصویر شاخص")
    )
    video_url = models.CharField(
        max_length=500, blank=True, default="", verbose_name=_("نشانی ویدیوی معرفی")
    )
    province = models.CharField(
        max_length=80, blank=True, default="", db_index=True, verbose_name=_("استان اجرا")
    )
    city = models.CharField(max_length=80, blank=True, default="", verbose_name=_("شهر/منطقه"))

    # ── ساختار سهم‌بندی و ارقام مالی (تمام مبالغ به ریال صحیح) ──────────────
    total_shares = models.PositiveIntegerField(verbose_name=_("کل تعداد سهم‌ها"))
    share_price_rial = models.BigIntegerField(verbose_name=_("مبلغ هر سهم (ریال)"))
    target_amount_rial = models.BigIntegerField(verbose_name=_("مبلغ هدف کل حرکت (ریال)"))
    min_shares_per_order = models.PositiveIntegerField(
        default=1, verbose_name=_("حداقل سهم در هر سفارش")
    )
    max_shares_per_order = models.PositiveIntegerField(
        default=0,
        help_text=_("صفر به معنای مجاز بودن خرید تا سقف سهم‌های باقی‌مانده است."),
        verbose_name=_("حداکثر سهم در هر سفارش"),
    )

    # شمارنده‌های اتمیک سهم‌ها
    paid_shares = models.PositiveIntegerField(default=0, verbose_name=_("سهم‌های پرداخت‌شده آنلاین"))
    matched_shares = models.PositiveIntegerField(
        default=0, verbose_name=_("سهم‌های مضاعف‌شده توسط حامی")
    )
    external_shares = models.PositiveIntegerField(
        default=0, verbose_name=_("سهم‌های تأمین‌شده خارج از درگاه")
    )
    reserved_shares = models.PositiveIntegerField(
        default=0, verbose_name=_("سهم‌های رزرو موقت در درگاه")
    )

    # ارقام تجمیعی ریالی
    collected_online_rial = models.BigIntegerField(
        default=0, verbose_name=_("مبلغ جذب‌شده آنلاین (ریال)")
    )
    matched_amount_rial = models.BigIntegerField(
        default=0, verbose_name=_("مبلغ مضاعف‌شده توسط حامی (ریال)")
    )
    external_amount_rial = models.BigIntegerField(
        default=0, verbose_name=_("مبلغ جذب‌شده خارجی/آفلاین (ریال)")
    )
    disbursed_amount_rial = models.BigIntegerField(
        default=0, verbose_name=_("مبلغ تسویه‌شده با خیریه (ریال)")
    )
    supporter_count = models.PositiveIntegerField(default=0, verbose_name=_("تعداد مشارکت‌های موفق"))
    physical_progress_percent = models.PositiveSmallIntegerField(
        default=0, verbose_name=_("درصد پیشرفت اجرای میدانی")
    )

    status = models.CharField(
        max_length=20,
        choices=CampaignStatus.choices,
        default=CampaignStatus.DRAFT,
        db_index=True,
        verbose_name=_("وضعیت حرکت"),
    )
    urgency_level = models.CharField(
        max_length=16,
        choices=CampaignUrgency.choices,
        default=CampaignUrgency.NORMAL,
        db_index=True,
        verbose_name=_("سطح فوریت"),
    )
    is_featured = models.BooleanField(default=False, db_index=True, verbose_name=_("نمایش ویژه"))
    allow_anonymous = models.BooleanField(default=True, verbose_name=_("امکان مشارکت ناشناس"))
    allow_dedication = models.BooleanField(
        default=True, verbose_name=_("امکان ثبت نیت‌نامه و هدیه معنوی")
    )
    starts_at = models.DateTimeField(null=True, blank=True, verbose_name=_("زمان شروع جذب"))
    ends_at = models.DateTimeField(
        null=True, blank=True, db_index=True, verbose_name=_("مهلت پایانی جذب")
    )
    completed_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("زمان تکمیل ظرفیت سهم‌ها")
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_campaigns",
        verbose_name=_("ایجادکننده"),
    )

    class Meta:
        verbose_name = _("حرکت خیرخواهانه")
        verbose_name_plural = _("حرکت‌های خیرخواهانه")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "urgency_level", "ends_at"], name="camp_status_urg_idx"),
            models.Index(fields=["benefactor", "status"], name="camp_benef_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(total_shares__gte=1) & Q(share_price_rial__gte=10_000),
                name="camp_positive_share_spec_chk",
            ),
            models.CheckConstraint(
                condition=Q(target_amount_rial=F("total_shares") * F("share_price_rial")),
                name="camp_target_equals_shares_mul_price_chk",
            ),
            models.CheckConstraint(
                condition=Q(
                    total_shares__gte=(
                        F("paid_shares")
                        + F("matched_shares")
                        + F("external_shares")
                        + F("reserved_shares")
                    )
                ),
                name="camp_shares_never_exceed_total_chk",
            ),
            models.CheckConstraint(
                condition=Q(physical_progress_percent__lte=100),
                name="camp_physical_progress_le_100_chk",
            ),
            models.CheckConstraint(
                condition=(
                    Q(collected_online_rial__gte=0)
                    & Q(matched_amount_rial__gte=0)
                    & Q(external_amount_rial__gte=0)
                    & Q(disbursed_amount_rial__gte=0)
                ),
                name="camp_non_negative_amounts_chk",
            ),
        ]

    def __str__(self) -> str:
        """نمایش عنوان و کد کوتاه حرکت."""
        return f"{self.title} [{self.short_code}]"

    @property
    def funded_shares(self) -> int:
        """مجموع سهم‌های قطعی تأمین‌شده (آنلاین + مضاعف + خارجی)."""
        return int(self.paid_shares + self.matched_shares + self.external_shares)

    @property
    def remaining_shares(self) -> int:
        """تعداد سهم‌های آزاد قابل خرید در همین لحظه (با کسر رزروهای فعال ۱۵ دقیقه‌ای)."""
        rem = self.total_shares - self.funded_shares - self.reserved_shares
        return max(0, int(rem))

    @property
    def total_funded_rial(self) -> int:
        """مجموع ریالی کل منابع تأمین‌شده (آنلاین + مضاعف + خارجی)."""
        return int(
            self.collected_online_rial + self.matched_amount_rial + self.external_amount_rial
        )

    @property
    def progress_percent(self) -> float:
        """درصد پیشرفت تأمین سهم‌ها (با دقت دو رقم اعشار)."""
        if self.total_shares <= 0:
            return 0.0
        return round(min(100.0, (self.funded_shares / self.total_shares) * 100.0), 2)

    @property
    def has_financial_activity(self) -> bool:
        """آیا تاکنون سهمی در این حرکت رزرو یا پرداخت شده است؟"""
        return (
            self.paid_shares > 0
            or self.matched_shares > 0
            or self.external_shares > 0
            or self.reserved_shares > 0
        )


class CampaignMedia(BaseModel):
    """تصاویر، ویدیوها و مستندات رسمی پیوست‌شده به صفحهٔ حرکت."""

    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name="media_items",
        verbose_name=_("حرکت"),
    )
    kind = models.CharField(
        max_length=16,
        choices=CampaignMediaKind.choices,
        default=CampaignMediaKind.IMAGE,
        verbose_name=_("نوع رسانه"),
    )
    url = models.CharField(max_length=500, verbose_name=_("نشانی فایل"))
    caption = models.CharField(
        max_length=240, blank=True, default="", verbose_name=_("زیرنویس / توضیح")
    )
    display_order = models.PositiveIntegerField(default=100, verbose_name=_("ترتیب نمایش"))

    class Meta:
        verbose_name = _("رسانهٔ حرکت")
        verbose_name_plural = _("رسانه‌های حرکت")
        ordering = ["display_order", "created_at"]

    def __str__(self) -> str:
        """نمایش نوع و حرکت مربوطه."""
        return f"{self.kind} @ {self.campaign_id}"


class MatchingGrant(BaseModel):
    """تعهد حامی مضاعف‌کننده (Corporate/Philanthropist Match Pool) برای دوبرابر کردن اثر خیرین."""

    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name="matching_grants",
        verbose_name=_("حرکت هدف"),
    )
    sponsor_name = models.CharField(max_length=180, verbose_name=_("نام حامی مضاعف‌کننده"))
    sponsor_logo_url = models.CharField(
        max_length=500, blank=True, default="", verbose_name=_("نشانی لوگوی حامی")
    )
    match_ratio = models.PositiveSmallIntegerField(
        default=1,
        help_text=_("به ازای هر ۱ سهم خریداری‌شده توسط خیر، چند سهم از محل این تعهد آزاد شود."),
        verbose_name=_("ضریب برابری سهم"),
    )
    total_pool_shares = models.PositiveIntegerField(verbose_name=_("سقف کل سهم‌های تعهدشده"))
    consumed_shares = models.PositiveIntegerField(
        default=0, verbose_name=_("سهم‌های مصرف‌شده تا این لحظه")
    )
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("فعال"))
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name=_("تاریخ انقضای تعهد"))

    class Meta:
        verbose_name = _("حامی مضاعف‌کننده")
        verbose_name_plural = _("حامیان مضاعف‌کننده")
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(match_ratio__gte=1)
                    & Q(total_pool_shares__gte=1)
                    & Q(consumed_shares__lte=F("total_pool_shares"))
                ),
                name="matching_grant_pool_bounds_chk",
            ),
        ]

    def __str__(self) -> str:
        """نمایش نام حامی و ظرفیت مصرف‌شده."""
        return f"{self.sponsor_name} ({self.consumed_shares}/{self.total_pool_shares})"

    @property
    def remaining_pool_shares(self) -> int:
        """تعداد سهم باقی‌مانده در استخر مضاعف‌سازی حامی."""
        return max(0, int(self.total_pool_shares - self.consumed_shares))


class CampaignImpactUpdate(BaseModel):
    """گزارش تصویری و مرحله‌ای پیشرفت اجرای میدانی حرکت برای اطلاع‌رسانی به سهام‌داران."""

    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name="impact_updates",
        verbose_name=_("حرکت"),
    )
    milestone_type = models.CharField(
        max_length=32,
        choices=ImpactMilestoneType.choices,
        default=ImpactMilestoneType.FIELD_DELIVERY,
        verbose_name=_("نوع مرحلهٔ اجرا"),
    )
    title = models.CharField(max_length=200, verbose_name=_("عنوان گزارش"))
    body = models.TextField(verbose_name=_("شرح گزارش میدانی"))
    progress_percent = models.PositiveSmallIntegerField(
        default=0, verbose_name=_("درصد پیشرفت فیزیکی اجرا")
    )
    spent_amount_rial = models.BigIntegerField(
        default=0, verbose_name=_("مبلغ هزینه‌شده در این مرحله (ریال)")
    )
    media_urls = models.JSONField(
        default=list, blank=True, verbose_name=_("فهرست تصاویر/ویدیوهای مستند")
    )
    is_published = models.BooleanField(default=True, db_index=True, verbose_name=_("منتشرشده"))
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_impact_updates",
        verbose_name=_("منتشرکننده"),
    )

    class Meta:
        verbose_name = _("گزارش پیشرفت میدانی")
        verbose_name_plural = _("گزارش‌های پیشرفت میدانی")
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(progress_percent__lte=100) & Q(spent_amount_rial__gte=0),
                name="impact_update_bounds_chk",
            ),
        ]

    def __str__(self) -> str:
        """نمایش عنوان گزارش پیشرفت."""
        return f"{self.title} ({self.progress_percent}%)"
