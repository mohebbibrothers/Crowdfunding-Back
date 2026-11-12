"""مدل‌های تغییرناپذیر زنجیرهٔ حسابرسی (AuditRecord) و لنگر امضاشده (AuditAnchor)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.audit.choices import AuditAction, AuditOutcome
from apps.core.models import BaseModel

GENESIS_HASH = "0" * 64


def canonical_json(payload: dict[str, Any]) -> str:
    """سریال‌سازی قطعی و متعارف دیکشنری برای محاسبهٔ هش تغییرناپذیر."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_record_hash(*, previous_hash: str, payload: dict[str, Any]) -> str:
    """محاسبهٔ هش SHA-256 رکورد حسابرسی زنجیره‌شده به هش رکورد قبلی."""
    raw = f"v1|{previous_hash}|{canonical_json(payload)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AuditRecord(BaseModel):
    """رکورد تک‌افزودنی (Append-Only) زنجیرهٔ هش حسابرسی."""

    sequence = models.PositiveBigIntegerField(
        unique=True, db_index=True, verbose_name=_("شمارهٔ ترتیب")
    )
    action = models.CharField(
        max_length=80, choices=AuditAction.choices, db_index=True, verbose_name=_("کنش")
    )
    outcome = models.CharField(
        max_length=20,
        choices=AuditOutcome.choices,
        default=AuditOutcome.SUCCESS,
        verbose_name=_("نتیجه"),
    )
    actor_id = models.UUIDField(null=True, blank=True, db_index=True, verbose_name=_("شناسهٔ کنش‌گر"))
    actor_label = models.CharField(
        max_length=120, blank=True, default="", verbose_name=_("نام نمایشی کنش‌گر")
    )
    target_type = models.CharField(
        max_length=64, blank=True, default="", db_index=True, verbose_name=_("نوع هدف")
    )
    target_id = models.CharField(
        max_length=64, blank=True, default="", db_index=True, verbose_name=_("شناسهٔ هدف")
    )
    reason = models.CharField(max_length=500, blank=True, default="", verbose_name=_("دلیل ثبت‌شده"))
    metadata = models.JSONField(default=dict, blank=True, verbose_name=_("فرادادهٔ پاک‌سازی‌شده"))
    request_id = models.CharField(
        max_length=64, blank=True, default="", verbose_name=_("شناسهٔ درخواست")
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name=_("آدرس IP"))
    user_agent = models.CharField(max_length=300, blank=True, default="", verbose_name=_("مرورگر"))
    previous_hash = models.CharField(max_length=64, verbose_name=_("هش رکورد قبلی"))
    record_hash = models.CharField(max_length=64, unique=True, verbose_name=_("هش رکورد جاری"))

    class Meta:
        verbose_name = _("رکورد حسابرسی")
        verbose_name_plural = _("رکوردهای حسابرسی")
        ordering = ["-sequence"]
        indexes = [
            models.Index(fields=["action", "-sequence"], name="audit_action_seq_idx"),
            models.Index(fields=["target_type", "target_id"], name="audit_target_idx"),
        ]

    def __str__(self) -> str:
        """نمایش شمارهٔ ترتیب و کنش."""
        return f"#{self.sequence} {self.action}"

    def payload_for_hash(self) -> dict[str, Any]:
        """ساخت محمولهٔ متعارف جهت محاسبه و راستی‌آزمایی هش رکورد."""
        created_iso = self.created_at.isoformat() if self.created_at else ""
        return {
            "sequence": self.sequence,
            "action": self.action,
            "outcome": self.outcome,
            "actor_id": str(self.actor_id) if self.actor_id else None,
            "actor_label": self.actor_label,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "reason": self.reason,
            "metadata": self.metadata,
            "request_id": self.request_id,
            "created_at": created_iso,
        }

    def verify_integrity(self) -> bool:
        """بررسی تطابق هش ذخیره‌شده با محتوای واقعی رکورد."""
        expected = compute_record_hash(
            previous_hash=self.previous_hash, payload=self.payload_for_hash()
        )
        return expected == self.record_hash

    def save(self, *args: Any, **kwargs: Any) -> None:
        """محافظت از تغییرناپذیری رکورد پس از ثبت نهایی هش."""
        if not self._state.adding:
            update_fields = set(kwargs.get("update_fields") or [])
            if update_fields != {"record_hash", "updated_at"}:
                msg = "ویرایش رکورد حسابرسی ثبت‌شده مجاز نیست (Append-Only)."
                raise PermissionError(msg)
        super().save(*args, **kwargs)

    def delete(self, using: Any = None, keep_parents: bool = False) -> tuple[int, dict[str, int]]:
        """جلوگیری مطلق از حذف نرم یا فیزیکی رکوردهای حسابرسی."""
        del using, keep_parents
        msg = "حذف رکوردهای زنجیرهٔ حسابرسی مطلقاً ممنوع است."
        raise PermissionError(msg)


class AuditAnchor(BaseModel):
    """لنگر روزانهٔ امضاشده با HMAC برای کشف حذف احتمالی انتهای زنجیرهٔ حسابرسی."""

    last_sequence = models.PositiveBigIntegerField(unique=True, verbose_name=_("آخرین شمارهٔ ترتیب"))
    last_hash = models.CharField(max_length=64, verbose_name=_("آخرین هش زنجیره"))
    record_count = models.PositiveBigIntegerField(verbose_name=_("تعداد کل رکوردها"))
    anchored_at = models.DateTimeField(default=timezone.now, verbose_name=_("زمان لنگرگذاری"))
    signature = models.CharField(max_length=64, verbose_name=_("امضای HMAC لنگر"))

    class Meta:
        verbose_name = _("لنگر حسابرسی")
        verbose_name_plural = _("لنگرهای حسابرسی")
        ordering = ["-last_sequence"]

    def __str__(self) -> str:
        """نمایش شمارهٔ ترتیب لنگر."""
        return f"Anchor@{self.last_sequence}"

    def payload_for_signature(self) -> dict[str, Any]:
        """محمولهٔ متعارف جهت امضای HMAC لنگر."""
        return {
            "last_sequence": self.last_sequence,
            "last_hash": self.last_hash,
            "record_count": self.record_count,
            "anchored_at": self.anchored_at.isoformat(),
        }
