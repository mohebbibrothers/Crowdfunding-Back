"""صندوق خروجی تراکنشی (Transactional Outbox) — تضمین تحویل رخدادها بدون گره‌خوردن به شبکه."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import logging
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone

from apps.core.choices import OutboxStatus
from apps.core.models import OutboxMessage

logger = logging.getLogger(__name__)

OutboxHandler = Callable[[OutboxMessage], None]
_HANDLERS: dict[str, list[OutboxHandler]] = {}
MAX_OUTBOX_ATTEMPTS = 8


def register_outbox_handler(event_type: str, handler: OutboxHandler) -> None:
    """ثبت پردازشگر برای یک نوع رخداد دامنه‌ای در رجیستری صندوق خروجی."""
    bucket = _HANDLERS.setdefault(event_type, [])
    if handler not in bucket:
        bucket.append(handler)


def enqueue_outbox(
    *,
    event_type: str,
    payload: dict[str, Any],
    aggregate_type: str = "",
    aggregate_id: str = "",
    dedup_key: str | None = None,
) -> OutboxMessage | None:
    """درج پیام در جدول Outbox درون همان تراکنش دیتابیسی بدون لمس شبکه."""
    cleaned_dedup = (dedup_key or "").strip() or None
    if cleaned_dedup and OutboxMessage.all_objects.filter(dedup_key=cleaned_dedup).exists():
        return None
    try:
        with transaction.atomic():
            return OutboxMessage.objects.create(
                event_type=event_type,
                aggregate_type=aggregate_type[:64],
                aggregate_id=str(aggregate_id)[:64],
                dedup_key=cleaned_dedup,
                payload=payload,
                status=OutboxStatus.PENDING,
            )
    except IntegrityError:
        return None


def drain_outbox(*, batch_size: int = 100) -> dict[str, int]:
    """پردازش دسته‌ای پیام‌های آمادهٔ ارسال در صندوق خروجی (ایمن برای Cron با flock)."""
    stats = {"delivered": 0, "failed": 0, "dead": 0}
    now = timezone.now()

    candidate_ids = list(
        OutboxMessage.objects.filter(
            status__in=[OutboxStatus.PENDING, OutboxStatus.FAILED],
            available_at__lte=now,
        )
        .order_by("created_at")
        .values_list("id", flat=True)[:batch_size]
    )

    for message_id in candidate_ids:
        with transaction.atomic():
            msg = (
                OutboxMessage.objects.select_for_update()
                .filter(
                    pk=message_id,
                    status__in=[OutboxStatus.PENDING, OutboxStatus.FAILED],
                )
                .first()
            )
            if msg is None:
                continue
            msg.status = OutboxStatus.PROCESSING
            msg.attempts += 1
            msg.save(update_fields=["status", "attempts", "updated_at"])

        handlers = _HANDLERS.get(msg.event_type, [])
        try:
            for handler in handlers:
                handler(msg)
            msg.status = OutboxStatus.DELIVERED
            msg.processed_at = timezone.now()
            msg.last_error = ""
            msg.save(update_fields=["status", "processed_at", "last_error", "updated_at"])
            stats["delivered"] += 1
        except Exception as exc:
            logger.exception(
                "outbox_delivery_failed",
                extra={"event_type": msg.event_type, "outbox_id": str(msg.pk)},
            )
            if msg.attempts >= MAX_OUTBOX_ATTEMPTS:
                msg.status = OutboxStatus.DEAD
                stats["dead"] += 1
            else:
                backoff_seconds = min(30 * (2 ** max(msg.attempts - 1, 0)), 3600)
                msg.status = OutboxStatus.FAILED
                msg.available_at = timezone.now() + timedelta(seconds=backoff_seconds)
                stats["failed"] += 1
            msg.last_error = str(exc)[:1000]
            msg.save(update_fields=["status", "available_at", "last_error", "updated_at"])

    return stats


@transaction.atomic
def requeue_outbox_messages(*, message_ids: list[Any]) -> dict[str, Any]:
    """بازگردانی پیام‌های متوقف‌شدهٔ ``DEAD`` به صف پردازش (عملیات نجات انسانی).

    چرا لازم است؟
        ``drain_outbox`` پس از ``MAX_OUTBOX_ATTEMPTS`` پیام را ``DEAD`` می‌کند و
        تا پیش از این هیچ مسیر رسمی‌ای برای نجاتش وجود نداشت؛ تنها راه، دست‌زدن
        مستقیم به دیتابیس بود. پیام DEAD ممکن است یک «تأیید پرداخت» یا «رسید خیر»
        باشد — یعنی چیزی که نباید بی‌صدا بماند.

    ایمنی:
        • شمارندهٔ تلاش صفر می‌شود ولی تاریخچهٔ خطا در ``last_error`` می‌ماند.
        • ثبت حسابرسی توسط لایهٔ فراخوان (پنل ادمین) انجام می‌شود تا این ماژول
          در گراف وابستگی هسته، به ``apps.audit`` وابسته نشود (انضباط DAG).
    """
    now = timezone.now()
    clean_ids = [mid for mid in message_ids if mid]
    if not clean_ids:
        return {"requeued": 0, "skipped": 0}

    targets = list(
        OutboxMessage.objects.select_for_update().filter(
            pk__in=clean_ids,
            status=OutboxStatus.DEAD,
        )
    )
    if not targets:
        return {"requeued": 0, "skipped": len(clean_ids)}

    for msg in targets:
        msg.status = OutboxStatus.PENDING
        msg.attempts = 0
        msg.available_at = now
        msg.last_error = (f"[requeued] {msg.last_error}")[:1000]
        msg.save(update_fields=["status", "attempts", "available_at", "last_error", "updated_at"])

    return {
        "requeued": len(targets),
        "skipped": len(clean_ids) - len(targets),
        "requeued_ids": [str(m.pk) for m in targets],
    }


def outbox_health_snapshot() -> dict[str, int]:
    """شمارش پیام‌ها به تفکیک وضعیت برای پنل سلامت و متریک Prometheus."""
    counts = {
        str(row["status"]): int(row["n"])
        for row in OutboxMessage.objects.values("status").annotate(n=Count("id"))
    }
    for status in OutboxStatus.values:
        counts.setdefault(status, 0)
    return counts
