"""متریک‌های Prometheus برای پایش ترافیک، تأخیر، خطاها و تراکنش‌های مالی."""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

HTTP_REQUESTS_TOTAL = Counter(
    "crowdfunding_http_requests_total",
    "شمار کل درخواست‌های HTTP به تفکیک متد، مسیر الگو و کد وضعیت",
    ["method", "route", "status"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "crowdfunding_http_request_duration_seconds",
    "توزیع زمان پاسخ‌دهی درخواست‌های HTTP بر حسب ثانیه",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
LEDGER_POSTINGS_TOTAL = Counter(
    "crowdfunding_ledger_postings_total",
    "شمار کل ردیف‌های ثبت‌شده در دفتر کل دوطرفه",
    ["entry_kind"],
)
CONTRIBUTIONS_CONFIRMED_TOTAL = Counter(
    "crowdfunding_contributions_confirmed_total",
    "شمار مشارکت‌های قطعی‌شده به تفکیک نوع (حرکت سهم‌محور یا قلک خیریه)",
    ["kind"],
)


def render_prometheus_metrics() -> tuple[bytes, str]:
    """تولید متن استاندارد Prometheus برای نقطهٔ پایانی ``/metrics``."""
    _refresh_financial_gauges()
    return generate_latest(), CONTENT_TYPE_LATEST


# ── متریک‌های حلقهٔ نجات وجه (Capture Recovery) ────────────────────────────────
LATE_CAPTURE_RECOVERIES_TOTAL = Counter(
    "crowdfunding_late_capture_recoveries_total",
    "شمار نتیجهٔ داوری پرداخت‌های رهاشده به تفکیک نوع تصمیم",
    ["outcome"],
)
REFUND_DISPATCH_TOTAL = Counter(
    "crowdfunding_refund_dispatch_total",
    "شمار تلاش‌های ارسال بازپرداخت به درگاه به تفکیله نتیجه",
    ["result"],
)
# گیج‌ها هنگام جمع‌آوری (/metrics) از دیتابیس پر می‌شوند تا همیشه «حقیقت جاری» باشند.
PENDING_REFUND_OBLIGATIONS = Gauge(
    "crowdfunding_pending_refund_obligations",
    "تعداد تعهدهای بازپرداخت که هنوز تسویه نشده‌اند (هر عدد > ۰ = بدهی باز به حامی)",
)
UNRESOLVED_LATE_CAPTURES = Gauge(
    "crowdfunding_unresolved_late_captures",
    "تعداد پرداخت‌های رهاشده که هنوز داوری نهایی نشده‌اند",
)
ABANDONED_PAYMENTS = Gauge(
    "crowdfunding_abandoned_payments",
    "تعداد پرداخت‌های با وضعیت پول نامعلوم (ABANDONED)",
)
REFUND_LIABILITY_RIAL = Gauge(
    "crowdfunding_refund_liability_rial",
    "مجموع ریالی تعهدهای بازپرداخت باز؛ معادل بدهی سامانه به حامیان",
)
OUTBOX_BY_STATUS = Gauge(
    "crowdfunding_outbox_messages",
    "تعداد پیام‌های صندوق خروجی به تفکیک وضعیت",
    ["status"],
)


def _refresh_financial_gauges() -> None:
    """تازه‌سازی گیج‌های مالی از دیتابیس پیش از تولید خروجی ``/metrics``.

    چرا در زمان جمع‌آوری و نه در زمان رخداد؟
        شمارنده‌ها برای رخداد خوب‌اند، ولی «چند تعهد بازپرداخت باز داریم؟» یک
        وضعیت است، نه رخداد. اگر آن را Gauge رخدادی کنیم، هر ری‌استارت یا
        مایگریشن آن را صفر می‌کند و هشدار دروغ می‌شود.
    """
    try:
        from apps.contributions.choices import LateCaptureOutcome, PaymentStatus, RefundOutcome
        from apps.contributions.models import LateCaptureRecovery, Payment, PaymentRefund
        from apps.core.outbox import outbox_health_snapshot

        pending = PaymentRefund.objects.filter(outcome=RefundOutcome.PENDING)
        PENDING_REFUND_OBLIGATIONS.set(pending.count())
        REFUND_LIABILITY_RIAL.set(int(sum(int(p.amount_rial) for p in pending.only("amount_rial"))))
        UNRESOLVED_LATE_CAPTURES.set(
            LateCaptureRecovery.objects.filter(outcome=LateCaptureOutcome.MANUAL_REVIEW).count()
        )
        ABANDONED_PAYMENTS.set(Payment.objects.filter(status=PaymentStatus.ABANDONED).count())
        for status, count in outbox_health_snapshot().items():
            OUTBOX_BY_STATUS.labels(status=status).set(count)
    except Exception:
        return
