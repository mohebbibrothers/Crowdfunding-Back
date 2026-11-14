"""متریک‌های Prometheus برای پایش ترافیک، تأخیر، خطاها و تراکنش‌های مالی."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

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


# رجیستری پورت «حقیقت وجه»: اپ مشارکت‌ها آن را در زمان بارگذاری ثبت می‌کند.
# این الگو (Port Registry) همان چیزی است که چرخهٔ وابستگی را به لبهٔ زمان‌اجرا
# تبدیل می‌کند؛ core هیچ‌گاه از contributions import نمی‌کند.
_MONEY_TRUTH_PROVIDER: Callable[[], dict[str, Any]] | None = None


def register_money_truth_provider(provider: Callable[[], dict[str, Any]]) -> None:
    """ثبت تأمین‌کنندهٔ عکس «حقیقت وجه» توسط اپ مشارکت‌ها."""
    global _MONEY_TRUTH_PROVIDER  # noqa: PLW0603
    _MONEY_TRUTH_PROVIDER = provider


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
# ── لایهٔ حقیقت وجه: آیا «تأییدشده» با صورت‌حساب مستقل هم‌خوان است؟ ──────────
SETTLEMENT_STATEMENT_AGE_HOURS = Gauge(
    "crowdfunding_settlement_statement_age_hours",
    "کهنگی آخرین صورت‌حساب تسویهٔ ورودی (ساعت)؛ -1 یعنی هیچ سندی وارد نشده",
)
PAYMENTS_TRUTH_CONFIRMED = Gauge(
    "crowdfunding_payments_truth_confirmed",
    "تعداد پرداخت‌هایی که صورت‌حساب مستقل تأییدشان کرده است",
)
PAYMENTS_TRUTH_UNCONFIRMED = Gauge(
    "crowdfunding_payments_truth_unconfirmed",
    "پرداخت‌های تأییدشدهٔ داخلی که هنوز تأیید مستقل ندارند",
)
PAYMENTS_TRUTH_CONFLICT = Gauge(
    "crowdfunding_payments_truth_conflict",
    "تناقض قطعی دفتر داخلی با صورت‌حساب مستقل — همیشه باید صفر باشد",
)
UNRESOLVED_FINANCIAL_IMPACT_RIAL = Gauge(
    "crowdfunding_unresolved_financial_impact_rial",
    "اثر ریالی مغایرت‌های حل‌نشدهٔ صورت‌حساب",
)
REFRESH_FAILURES_TOTAL = Counter(
    "crowdfunding_metrics_refresh_failures_total",
    "شمار شکست تازه‌سازی گیج‌های مالی از دیتابیس؛ هر مقدار > ۰ یعنی /metrics عدد کهنه نشان می‌دهد",
    ["error_type"],
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

        # لایهٔ حقیقت وجه — از طریق رجیستری پورت خوانده می‌شود، نه import مستقیم.
        # چرا؟ چون ``contributions.settlement`` برای خوددرمانی به ``contributions.services``
        # ارجاع می‌دهد و آن زنجیره از ``audit.services`` → ``core.middleware`` به این
        # ماژول برمی‌گردد. import مستقیم، چرخهٔ واقعی می‌سازد؛ رجیستری پورت آن را
        # به یک لبهٔ زمان‌اجرا تبدیل می‌کند که گیت DAG هم آن را نمی‌بیند.
        truth = _MONEY_TRUTH_PROVIDER() if _MONEY_TRUTH_PROVIDER is not None else None
        if truth is not None:
            SETTLEMENT_STATEMENT_AGE_HOURS.set(
                -1.0
                if truth["statement_age_hours"] is None
                else float(truth["statement_age_hours"])
            )
            PAYMENTS_TRUTH_CONFIRMED.set(int(truth["statement_confirmed"]))
            PAYMENTS_TRUTH_UNCONFIRMED.set(int(truth["verified_but_unconfirmed"]))
            PAYMENTS_TRUTH_CONFLICT.set(int(truth["conflict"]))
            UNRESOLVED_FINANCIAL_IMPACT_RIAL.set(int(truth["unresolved_impact_rial"]))
    except Exception as exc:
        # ── هرگز سکوت نکن ────────────────────────────────────────────────────
        # پیش‌تر اینجا ``return`` خالی بود. نتیجه: اگر یک کوئری شکست می‌خورد،
        # همهٔ گیج‌ها روی مقدار قبلی (یا صفر) می‌ماندند و هیچ‌کس نمی‌فهمید که
        # /metrics دروغ می‌گوید. یک مانیتورینگ دروغ، از نبود مانیتورینگ بدتر است.
        # حالا شکست را در یک شمارندهٔ عمومی ثبت می‌کنیم تا خودش قابل هشدار باشد.
        REFRESH_FAILURES_TOTAL.labels(error_type=type(exc).__name__).inc()
        import logging

        logging.getLogger(__name__).warning("metrics gauge refresh failed: %s", exc, exc_info=True)
        return
