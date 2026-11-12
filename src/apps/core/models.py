"""مدل‌های پایهٔ هستهٔ مشترک: BaseModel با UUIDv7 و حذف نرم، قفل سریال، Outbox، هم‌توانی و Policy."""

from __future__ import annotations

from typing import Any, Self, TypeVar

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.choices import OutboxStatus, PolicyValueType
from apps.core.uuid7 import uuid7

_ModelT = TypeVar("_ModelT", bound=models.Model)


class SoftDeleteQuerySet(models.QuerySet[_ModelT]):
    """کوئری‌ست پشتیبان حذف نرم با متد صریح ``hard_delete`` برای پاک‌سازی فیزیکی."""

    def delete(self) -> tuple[int, dict[str, int]]:
        """علامت‌گذاری رکوردها به‌عنوان حذف‌شدهٔ نرم بدون حذف فیزیکی ردیف دیتابیس."""
        now = timezone.now()
        updated = super().update(deleted_at=now, updated_at=now)
        return updated, {self.model._meta.label: updated}

    def hard_delete(self) -> tuple[int, dict[str, int]]:
        """حذف فیزیکی ردیف‌ها از پایگاه‌داده (فقط برای رکوردهای موقت مثل کلید هم‌توانی منقضی)."""
        return super().delete()

    def alive(self) -> Self:
        """فیلتر رکوردهای فعال (حذف‌نشده)."""
        return self.filter(deleted_at__isnull=True)


class ActiveManager(models.Manager[_ModelT]):
    """مدیر پیش‌فرض مدل‌ها که رکوردهای حذف‌شدهٔ نرم را پنهان می‌کند."""

    def get_queryset(self) -> SoftDeleteQuerySet[_ModelT]:
        """برگرداندن کوئری‌ست فیلترشده روی ``deleted_at__isnull=True``."""
        return SoftDeleteQuerySet(self.model, using=self._db).alive()


class AllObjectsManager(models.Manager[_ModelT]):
    """مدیر جامع شامل رکوردهای حذف‌شدهٔ نرم برای ممیزی و یکتایی."""

    def get_queryset(self) -> SoftDeleteQuerySet[_ModelT]:
        """برگرداندن تمام رکوردها بدون فیلتر حذف نرم."""
        return SoftDeleteQuerySet(self.model, using=self._db)


class BaseModel(models.Model):
    """مدل پایهٔ تمام موجودیت‌های دامنه‌ای با کلید اصلی یکنوا UUIDv7 و حذف نرم."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid7,
        editable=False,
        verbose_name=_("شناسه"),
    )
    created_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        editable=False,
        verbose_name=_("زمان ایجاد"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("آخرین ویرایش"),
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("زمان حذف نرم"),
    )

    objects = ActiveManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    @property
    def is_deleted(self) -> bool:
        """آیا رکورد به‌صورت نرم حذف شده است؟"""
        return self.deleted_at is not None

    def delete(self, using: Any = None, keep_parents: bool = False) -> tuple[int, dict[str, int]]:
        """حذف نرم نمونهٔ جاری."""
        del keep_parents
        self.deleted_at = timezone.now()
        self.save(using=using, update_fields=["deleted_at", "updated_at"])
        return 1, {self._meta.label: 1}

    def hard_delete(
        self, using: Any = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """حذف فیزیکی نمونهٔ جاری از پایگاه‌داده."""
        return super().delete(using=using, keep_parents=keep_parents)


class SerialLock(models.Model):
    """جدول قفل‌های تراکنشی نام‌دار برای سریال‌سازی زنجیرهٔ حسابرسی و شمارنده‌های بحرانی."""

    name = models.CharField(max_length=64, primary_key=True, verbose_name=_("نام قفل"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("زمان ساخت"))

    class Meta:
        db_table = "core_serial_lock"
        verbose_name = _("قفل سریال")
        verbose_name_plural = _("قفل‌های سریال")

    def __str__(self) -> str:
        """نمایش متنی نام قفل."""
        return self.name


class IdempotencyRecord(BaseModel):
    """رکورد کلید هم‌توانی برای تضمین «دوبار ارسال، یک‌بار اثر»."""

    key = models.CharField(max_length=128, verbose_name=_("کلید هم‌توانی"))
    scope = models.CharField(max_length=120, verbose_name=_("دامنهٔ مسیر"))
    actor_ref = models.CharField(max_length=64, blank=True, default="", verbose_name=_("کنش‌گر"))
    request_fingerprint = models.CharField(
        max_length=64, blank=True, default="", verbose_name=_("اثر انگشت بدنه")
    )
    response_status = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name=_("کد وضعیت پاسخ")
    )
    response_body = models.JSONField(null=True, blank=True, verbose_name=_("بدنهٔ پاسخ"))
    locked_at = models.DateTimeField(null=True, blank=True, verbose_name=_("زمان قفل"))
    expires_at = models.DateTimeField(db_index=True, verbose_name=_("زمان انقضا"))

    class Meta:
        verbose_name = _("رکورد هم‌توانی")
        verbose_name_plural = _("رکوردهای هم‌توانی")
        constraints = [
            models.UniqueConstraint(
                fields=["key", "scope"], name="uniq_core_idempotency_key_scope"
            ),
        ]
        indexes = [
            models.Index(fields=["expires_at"], name="core_idem_expires_idx"),
        ]

    def __str__(self) -> str:
        """نمایش کلید و دامنه."""
        return f"{self.scope}:{self.key}"


class OutboxMessage(BaseModel):
    """صندوق خروجی تراکنشی برای جداسازی کامل تراکنش‌های مالی از شبکهٔ بیرونی."""

    event_type = models.CharField(max_length=100, db_index=True, verbose_name=_("نوع رخداد"))
    aggregate_type = models.CharField(
        max_length=64, blank=True, default="", verbose_name=_("موجودیت")
    )
    aggregate_id = models.CharField(
        max_length=64, blank=True, default="", verbose_name=_("شناسهٔ موجودیت")
    )
    dedup_key = models.CharField(
        max_length=140, null=True, blank=True, unique=True, verbose_name=_("کلید عدم تکرار")
    )
    payload = models.JSONField(default=dict, verbose_name=_("محمولهٔ رخداد"))
    status = models.CharField(
        max_length=20,
        choices=OutboxStatus.choices,
        default=OutboxStatus.PENDING,
        db_index=True,
        verbose_name=_("وضعیت"),
    )
    attempts = models.PositiveSmallIntegerField(default=0, verbose_name=_("تعداد تلاش"))
    available_at = models.DateTimeField(
        default=timezone.now, db_index=True, verbose_name=_("زمان آمادگی اجرا")
    )
    processed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("زمان تکمیل"))
    last_error = models.TextField(blank=True, default="", verbose_name=_("آخرین خطا"))

    class Meta:
        verbose_name = _("پیام صندوق خروجی")
        verbose_name_plural = _("پیام‌های صندوق خروجی")
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status", "available_at"], name="core_outbox_ready_idx"),
        ]

    def __str__(self) -> str:
        """نمایش نوع رخداد و وضعیت."""
        return f"{self.event_type} [{self.status}]"


class PolicyRule(BaseModel):
    """قانون پویا و نسخه‌دار کسب‌وکار (Policy-as-Data) بدون نیاز به دیپلوی مجدد."""

    key = models.CharField(max_length=100, unique=True, verbose_name=_("کلید سیاست"))
    value_type = models.CharField(
        max_length=16,
        choices=PolicyValueType.choices,
        default=PolicyValueType.BOOL,
        verbose_name=_("نوع مقدار"),
    )
    raw_value = models.JSONField(verbose_name=_("مقدار جاری"))
    description = models.CharField(max_length=300, blank=True, default="", verbose_name=_("توضیح"))
    version = models.PositiveIntegerField(default=1, verbose_name=_("نسخه"))
    updated_by_id = models.UUIDField(null=True, blank=True, verbose_name=_("آخرین ویرایشگر"))

    class Meta:
        verbose_name = _("سیاست سامانه")
        verbose_name_plural = _("سیاست‌های سامانه")
        ordering = ["key"]

    def __str__(self) -> str:
        """نمایش کلید و نسخهٔ سیاست."""
        return f"{self.key} (v{self.version})"


class PolicyRevision(BaseModel):
    """تاریخچهٔ تغییرناپذیر ویرایش‌های سیاست‌ها همراه با دلیل اجباری مدیر."""

    policy = models.ForeignKey(
        PolicyRule,
        on_delete=models.PROTECT,
        related_name="revisions",
        verbose_name=_("سیاست"),
    )
    version = models.PositiveIntegerField(verbose_name=_("نسخه"))
    previous_value = models.JSONField(null=True, blank=True, verbose_name=_("مقدار پیشین"))
    new_value = models.JSONField(verbose_name=_("مقدار جدید"))
    reason = models.CharField(max_length=400, verbose_name=_("دلیل تغییر"))
    changed_by_id = models.UUIDField(null=True, blank=True, verbose_name=_("تغییردهنده"))

    class Meta:
        verbose_name = _("نسخهٔ سیاست")
        verbose_name_plural = _("نسخه‌های سیاست")
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["policy", "version"], name="uniq_core_policy_revision_ver"
            ),
        ]

    def __str__(self) -> str:
        """نمایش کلید سیاست و شمارهٔ نسخه."""
        return f"{self.policy.key}@v{self.version}"
