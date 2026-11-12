"""موتور هم‌توانی (Idempotency-Key) برای تضمین «ارسال تکراری، اثر واحد» در عملیات مالی."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json
from typing import Any, cast

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.choices import IdempotencyOutcome
from apps.core.errors import ConflictError, IdempotencyConflictError
from apps.core.models import IdempotencyRecord, SoftDeleteQuerySet

IDEMPOTENCY_HEADER = "Idempotency-Key"
DEFAULT_TTL_HOURS = 24
STALE_LOCK_SECONDS = 120


@dataclass(frozen=True, slots=True)
class IdempotentResult:
    """خروجی اجرای یک عملیات هم‌توان برای بازگردانی در لایهٔ HTTP."""

    status: int
    body: Any
    replayed: bool


def compute_fingerprint(payload: Any, *, scope: str = "") -> str:
    """محاسبهٔ اثر انگشت متعارف SHA-256 از بدنهٔ درخواست و دامنهٔ مسیر."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(f"{scope}|{canonical}".encode()).hexdigest()


def reserve_idempotency_key(
    *,
    key: str,
    scope: str,
    actor_ref: str,
    payload: Any = None,
) -> tuple[IdempotencyOutcome, IdempotencyRecord | None]:
    """رزرو اتمیک کلید هم‌توانی یا تشخیص بازپخش/تعارض/درجریان بودن."""
    fp = compute_fingerprint(payload, scope=scope) if payload is not None else ""
    now = timezone.now()
    expires = now + timedelta(hours=DEFAULT_TTL_HOURS)

    try:
        with transaction.atomic():
            record = IdempotencyRecord.all_objects.create(
                key=key[:128],
                scope=scope[:120],
                actor_ref=actor_ref[:64],
                request_fingerprint=fp,
                locked_at=now,
                expires_at=expires,
            )
        return IdempotencyOutcome.RESERVED, record
    except IntegrityError:
        existing = IdempotencyRecord.all_objects.filter(key=key[:128], scope=scope[:120]).first()
        if existing is None:  # pragma: no cover
            return IdempotencyOutcome.IN_PROGRESS, None
        return _evaluate_existing(existing, actor_ref=actor_ref[:64], fp=fp), existing


def _evaluate_existing(
    existing: IdempotencyRecord, *, actor_ref: str, fp: str
) -> IdempotencyOutcome:
    """ارزیابی رکورد موجود: حفاظت در برابر سرقت پاسخ بین دو کاربر و تصاحب قفل رهاشده."""
    if existing.actor_ref != actor_ref or (
        existing.request_fingerprint and fp and existing.request_fingerprint != fp
    ):
        return IdempotencyOutcome.CONFLICT
    if existing.response_status is not None:
        return IdempotencyOutcome.REPLAY

    now = timezone.now()
    expires = now + timedelta(hours=DEFAULT_TTL_HOURS)
    reclaimed = IdempotencyRecord.all_objects.filter(
        pk=existing.pk,
        response_status__isnull=True,
        locked_at__lt=now - timedelta(seconds=STALE_LOCK_SECONDS),
    ).update(locked_at=now, expires_at=expires)
    if not reclaimed:
        return IdempotencyOutcome.IN_PROGRESS
    existing.locked_at = now
    existing.expires_at = expires
    return IdempotencyOutcome.RESERVED


def release_idempotency_key(record: IdempotencyRecord) -> None:
    """حذف فیزیکی کلید رزروشده در صورت بروز استثنای دامنه تا تلاش مجدد مسدود نشود."""
    stale = cast(
        "SoftDeleteQuerySet[IdempotencyRecord]",
        IdempotencyRecord.all_objects.filter(pk=record.pk, response_status__isnull=True),
    )
    stale.hard_delete()


def execute_idempotent(
    *,
    key: str | None,
    scope: str,
    actor_ref: str,
    payload: Any,
    action: Callable[[], tuple[int, Any]],
) -> IdempotentResult:
    """اجرای عملیات نوشتنی با پشتیبانی اختیاری یا اجباری از هدر ``Idempotency-Key``."""
    cleaned_key = (key or "").strip()
    if not cleaned_key:
        status_code, body = action()
        return IdempotentResult(status=status_code, body=body, replayed=False)

    outcome, record = reserve_idempotency_key(
        key=cleaned_key, scope=scope, actor_ref=actor_ref, payload=payload
    )
    if outcome is IdempotencyOutcome.REPLAY and record is not None:
        return IdempotentResult(
            status=int(record.response_status or 200),
            body=record.response_body,
            replayed=True,
        )
    if outcome is IdempotencyOutcome.CONFLICT:
        raise IdempotencyConflictError()
    if outcome is IdempotencyOutcome.IN_PROGRESS:
        raise ConflictError(
            "درخواست هم‌زمان با همین کلید در حال پردازش است؛ لحظاتی بعد تلاش کنید.",
            code="idempotency_in_progress",
        )

    try:
        status_code, body = action()
    except Exception:
        if record is not None:
            release_idempotency_key(record)
        raise

    if record is not None:
        record.response_status = status_code
        record.response_body = body
        record.save(update_fields=["response_status", "response_body", "updated_at"])
    return IdempotentResult(status=status_code, body=body, replayed=False)


def purge_expired_idempotency_keys(*, batch_size: int = 1000) -> int:
    """پاک‌سازی فیزیکی کلیدهای هم‌توانی منقضی‌شده در کارهای دوره‌ای Cron."""
    expired_ids = list(
        IdempotencyRecord.all_objects.filter(expires_at__lt=timezone.now())
        .order_by("expires_at")
        .values_list("id", flat=True)[:batch_size]
    )
    if not expired_ids:
        return 0
    qs = cast(
        "SoftDeleteQuerySet[IdempotencyRecord]",
        IdempotencyRecord.all_objects.filter(id__in=expired_ids),
    )
    deleted_count, _ = qs.hard_delete()
    return int(deleted_count)
