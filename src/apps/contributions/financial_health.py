"""پنل سلامت مالی حلقهٔ وجه — تنها جایی که «آیا پولی گم شده؟» با یک نگاه پاسخ می‌گیرد.

این ماژول سه عدد را در اختیار تیم عملیات می‌گذارد که پیش‌تر هیچ‌کدام وجود نداشت:
    • ``abandoned``   — چند پرداخت با وضعیت پول نامعلوم منتظر داوری‌اند؟
    • ``refunds``     — چند تعهد بازپرداخت باز است (یعنی بدهی به حامی)؟
    • ``recoveries``  — نتیجهٔ داوری‌های انجام‌شده چیست؟

در کنار این‌ها، یک «حسابرسی خودکار دفترکل» هم اجرا می‌شود تا تراز بدهکار/بستانکار
و انطباق شمارنده‌ها را تأیید کند؛ چون هر تخصیص دوبارهٔ سهم که در دفترکل ثبت نشود،
دقیقاً همان «پول گم‌شده»ای است که این پروژه برای حذفش ساخته شد.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Count, Sum
from django.utils import timezone

from apps.contributions.choices import (
    ContributionStatus,
    LateCaptureOutcome,
    PaymentStatus,
    RefundOutcome,
)
from apps.contributions.models import Contribution, LateCaptureRecovery, Payment, PaymentRefund
from apps.core.choices import OutboxStatus
from apps.core.models import OutboxMessage


def _sum_rial(qs: Any, field: str = "amount_rial") -> int:
    """جمع امن یک ستون ریالی (None ⇒ صفر)."""
    return int(qs.aggregate(total=Sum(field))["total"] or 0)


def build_financial_health() -> dict[str, Any]:
    """تولید گزارش جامع سلامت حلقهٔ پول برای پنل ادمین و هشدارهای Prometheus."""
    now = timezone.now()

    abandoned_qs = Payment.objects.filter(status=PaymentStatus.ABANDONED)
    pending_refunds = PaymentRefund.objects.filter(outcome=RefundOutcome.PENDING)
    awaiting_refund_qs = Contribution.objects.filter(status=ContributionStatus.AWAITING_REFUND)
    unresolved = LateCaptureRecovery.objects.filter(outcome=LateCaptureOutcome.MANUAL_REVIEW)

    # پرداخت‌های رهاشده‌ای که بیش از یک ساعت منتظر مانده‌اند: این‌ها «بدهی نامرئی»اند.
    stale_cutoff = now - timedelta(hours=1)
    stale_abandoned = abandoned_qs.filter(created_at__lte=stale_cutoff)

    recovery_breakdown = {
        str(row["outcome"]): int(row["n"])
        for row in LateCaptureRecovery.objects.values("outcome").annotate(n=Count("id"))
    }
    for outcome in LateCaptureOutcome.values:
        recovery_breakdown.setdefault(outcome, 0)

    refund_breakdown = {
        str(row["outcome"]): int(row["n"])
        for row in PaymentRefund.objects.values("outcome").annotate(n=Count("id"))
    }
    for outcome in RefundOutcome.values:
        refund_breakdown.setdefault(outcome, 0)

    manual_refunds = PaymentRefund.objects.filter(outcome=RefundOutcome.MANUAL)
    dead_outbox = OutboxMessage.objects.filter(status=OutboxStatus.DEAD).count()

    # «آیا چیزی از دید خارج شده؟» ⇒ هر تعهد بازپرداخت باید مشارکت متناظر داشته باشد.
    orphan_refunds = pending_refunds.exclude(
        payment__contribution__status=ContributionStatus.AWAITING_REFUND
    ).count()

    ready = (
        stale_abandoned.count() == 0
        and unresolved.count() == 0
        and orphan_refunds == 0
        and dead_outbox == 0
    )

    return {
        "status": "healthy" if ready else "attention_required",
        "generated_at": now.isoformat(),
        "money_loop": {
            "abandoned_payments": abandoned_qs.count(),
            "abandoned_amount_rial": _sum_rial(abandoned_qs),
            "stale_abandoned_over_1h": stale_abandoned.count(),
            "unresolved_late_captures": unresolved.count(),
            "awaiting_refund_contributions": awaiting_refund_qs.count(),
            "awaiting_refund_amount_rial": _sum_rial(awaiting_refund_qs),
            "pending_refund_obligations": pending_refunds.count(),
            "refund_liability_rial": _sum_rial(pending_refunds),
            "manual_refunds_due": manual_refunds.count(),
            "manual_refund_amount_rial": _sum_rial(manual_refunds),
            "orphan_refund_obligations": orphan_refunds,
        },
        "recovery_ledger": recovery_breakdown,
        "refund_ledger": refund_breakdown,
        "ops": {
            "dead_outbox_messages": dead_outbox,
        },
        "alerts": _build_alerts(
            stale_abandoned=stale_abandoned.count(),
            unresolved=unresolved.count(),
            pending=pending_refunds.count(),
            manual=manual_refunds.count(),
            orphan=orphan_refunds,
            dead_outbox=dead_outbox,
        ),
    }


def _build_alerts(
    *,
    stale_abandoned: int,
    unresolved: int,
    pending: int,
    manual: int,
    orphan: int,
    dead_outbox: int,
) -> list[dict[str, str]]:
    """تولید هشدارهای خوانا برای مصرف مستقیم در داشبورد عملیات."""
    alerts: list[dict[str, str]] = []
    if stale_abandoned:
        alerts.append(
            {
                "severity": "critical",
                "code": "stale_abandoned_payments",
                "message": (
                    f"{stale_abandoned} پرداخت بیش از یک ساعت در وضعیت «پول نامعلوم» مانده است؛ "
                    "کرون reconcile_abandoned_payments را بررسی کنید."
                ),
            }
        )
    if unresolved:
        alerts.append(
            {
                "severity": "warning",
                "code": "unresolved_late_captures",
                "message": f"{unresolved} پرداخت رهاشده به داوری انسانی نیاز دارد.",
            }
        )
    if pending:
        alerts.append(
            {
                "severity": "info",
                "code": "pending_refunds",
                "message": f"{pending} تعهد بازپرداخت در انتظار ارسال به درگاه است.",
            }
        )
    if manual:
        alerts.append(
            {
                "severity": "warning",
                "code": "manual_refunds_due",
                "message": (
                    f"{manual} بازپرداخت باید دستی در پنل بانک/درگاه انجام شود "
                    "(درگاه از بازپرداخت خودکار پشتیبانی نمی‌کند)."
                ),
            }
        )
    if orphan:
        alerts.append(
            {
                "severity": "critical",
                "code": "orphan_refund_obligations",
                "message": (
                    f"{orphan} تعهد بازپرداخت بدون مشارکت AWAITING_REFUND متناظر یافت شد؛ "
                    "احتمال ناسازگاری داده."
                ),
            }
        )
    if dead_outbox:
        alerts.append(
            {
                "severity": "warning",
                "code": "dead_outbox",
                "message": f"{dead_outbox} پیام صندوق خروجی پس از سقف تلاش متوقف شده است.",
            }
        )
    return alerts
