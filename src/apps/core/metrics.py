"""متریک‌های Prometheus برای پایش ترافیک، تأخیر، خطاها و تراکنش‌های مالی."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

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
    return generate_latest(), CONTENT_TYPE_LATEST
