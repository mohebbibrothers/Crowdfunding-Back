"""سرویس‌های ارسال پیامک از صندوق خروجی، ثبت لاگ ممیزی و مدیریت صندوق اعلان کاربر."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.utils import timezone

from apps.core.crypto import mask_phone
from apps.core.errors import NotFoundError
from apps.core.logging import redact_value
from apps.core.models import OutboxMessage
from apps.core.outbox import register_outbox_handler
from apps.identity.choices import OtpPurpose
from apps.notifications.choices import (
    SmsDeliveryStatus,
    SmsPatternCode,
    UserNotificationKind,
)
from apps.notifications.models import SmsDeliveryLog, UserNotification
from apps.notifications.providers import resolve_sms_provider


def dispatch_sms_pattern(
    *,
    phone: str,
    pattern_code: str,
    tokens: dict[str, str],
) -> SmsDeliveryLog:
    """ارسال پیامک الگومحور از طریق پورت فعال و ثبت رکورد ممیزی با شماره پوشانده‌شده."""
    provider = resolve_sms_provider()
    safe_tokens = redact_value("tokens", tokens)
    if not isinstance(safe_tokens, dict):
        safe_tokens = {}
    try:
        result = provider.send_pattern(phone=phone, pattern_key=pattern_code, tokens=tokens)
        return SmsDeliveryLog.objects.create(
            phone_masked=mask_phone(phone),
            pattern_code=pattern_code,
            provider_name=result.provider_name,
            status=SmsDeliveryStatus.MOCKED if result.mocked else SmsDeliveryStatus.SENT,
            provider_message_id=result.message_id,
            sanitized_tokens=safe_tokens,
        )
    except Exception as exc:
        SmsDeliveryLog.objects.create(
            phone_masked=mask_phone(phone),
            pattern_code=pattern_code,
            provider_name=getattr(settings_provider_name(), "lower", lambda: "http")(),
            status=SmsDeliveryStatus.FAILED,
            sanitized_tokens=safe_tokens,
            error_message=str(exc)[:400],
        )
        raise


def settings_provider_name() -> str:
    """نام ارائه‌دهندهٔ تنظیم‌شده در محیط."""
    from django.conf import settings

    return str(getattr(settings, "SMS_PROVIDER_NAME", "mock"))


def create_user_notification(
    *,
    user_id: UUID,
    kind: str,
    title: str,
    body: str,
    action_url: str = "",
    metadata: dict[str, Any] | None = None,
) -> UserNotification:
    """ایجاد اعلان درون‌برنامه‌ای در صندوق پیام خیر."""
    return UserNotification.objects.create(
        user_id=user_id,
        kind=kind,
        title=title[:200],
        body=body,
        action_url=action_url[:300],
        metadata=metadata or {},
    )


def mark_notification_read(*, user_id: UUID, notification_id: str) -> UserNotification:
    """علامت‌گذاری یک اعلان کاربر به‌عنوان مطالعه‌شده."""
    notif = UserNotification.objects.filter(user_id=user_id, pk=notification_id).first()
    if notif is None:
        raise NotFoundError("اعلان مورد نظر یافت نشد.")
    if notif.read_at is None:
        notif.read_at = timezone.now()
        notif.save(update_fields=["read_at", "updated_at"])
    return notif


def mark_all_notifications_read(*, user_id: UUID) -> int:
    """علامت‌گذاری تمام اعلان‌های خوانده‌نشدهٔ کاربر به‌عنوان مطالعه‌شده."""
    now = timezone.now()
    return int(
        UserNotification.objects.filter(user_id=user_id, read_at__isnull=True).update(
            read_at=now, updated_at=now
        )
    )


# ── پردازشگرهای ثبت‌شده در صندوق خروجی تراکنشی (Outbox Handlers) ────────────


def _handle_otp_outbox(msg: OutboxMessage) -> None:
    purpose = str(msg.payload.get("purpose", OtpPurpose.LOGIN))
    pattern = (
        SmsPatternCode.OTP_EXPRESS
        if purpose == OtpPurpose.EXPRESS_CHECKOUT
        else SmsPatternCode.OTP_LOGIN
    )
    dispatch_sms_pattern(
        phone=str(msg.payload["phone"]),
        pattern_code=pattern,
        tokens={"code": str(msg.payload["code"])},
    )


def _handle_receipt_outbox(msg: OutboxMessage) -> None:
    dispatch_sms_pattern(
        phone=str(msg.payload["phone"]),
        pattern_code=SmsPatternCode.RECEIPT_ISSUED,
        tokens={
            "campaign": str(msg.payload.get("campaign_title", ""))[:40],
            "receipt": str(msg.payload.get("receipt_number", "")),
        },
    )


def _handle_dedication_gift_outbox(msg: OutboxMessage) -> None:
    recipient_phone = str(msg.payload.get("recipient_phone") or "")
    if not recipient_phone:
        return
    dispatch_sms_pattern(
        phone=recipient_phone,
        pattern_code=SmsPatternCode.DEDICATION_GIFT,
        tokens={
            "honoree": str(msg.payload.get("honoree_name", ""))[:35],
            "campaign": str(msg.payload.get("campaign_title", ""))[:35],
            "link": str(msg.payload.get("public_url", "")),
        },
    )


def _handle_pledge_reminder_outbox(msg: OutboxMessage) -> None:
    """یادآوری محترمانهٔ قسط تعهد مستمر.

    متن الگو کوتاه است چون SMS فارسی هر کاراکترش حساب دارد و پیامک بلند
    به دو پیامک شکسته می‌شود — هزینهٔ خیریه دو برابر، پیام یکی.
    """
    phone = str(msg.payload.get("phone") or "")
    if not phone:
        return
    dispatch_sms_pattern(
        phone=phone,
        pattern_code=SmsPatternCode.PLEDGE_REMINDER,
        tokens={
            "amount": f"{int(msg.payload.get('amount_rial') or 0):,}",
            "target": str(msg.payload.get("target_title", ""))[:30],
            "date": str(msg.payload.get("due_date", "")),
        },
    )


def _handle_pledge_expired_outbox(msg: OutboxMessage) -> None:
    """اعلان انقضای تعهد — خیر باید بداند کمکش متوقف شده است."""
    from uuid import UUID

    raw_user_id = str(msg.payload.get("user_id") or "")
    if not raw_user_id:
        return
    user_id = UUID(raw_user_id)
    amount_toman = int(msg.payload.get("amount_rial") or 0) // 10
    create_user_notification(
        user_id=user_id,
        kind=UserNotificationKind.PLEDGE_EXPIRED,
        title="تعهد کمک مستمر شما متوقف شد",
        body=(
            f"تعهد کمک مستمر شما به مبلغ {amount_toman:,} تومان پس از "
            f"{int(msg.payload.get('consecutive_failures') or 0)} قسط پرداخت‌نشده "
            "متوقف شد. هر زمان بخواهید می‌توانید تعهد تازه‌ای بسازید."
        ),
        action_url="/me/pledges",
        metadata={"pledge_id": str(msg.payload.get("pledge_id") or "")},
    )


def register_notification_outbox_handlers() -> None:
    """اتصال پردازشگرهای پیامک به رجیستری مرکزی صندوق خروجی."""
    register_outbox_handler("sms.otp_requested", _handle_otp_outbox)
    register_outbox_handler("sms.receipt_issued", _handle_receipt_outbox)
    register_outbox_handler("sms.dedication_gift", _handle_dedication_gift_outbox)
    register_outbox_handler("sms.pledge_reminder", _handle_pledge_reminder_outbox)
    register_outbox_handler("notification.pledge_expired", _handle_pledge_expired_outbox)
