"""بررسی سلامت سه‌سطحی سامانه (Liveness، Readiness و Detailed Operational Health)."""

from __future__ import annotations

from typing import Any

from django.core.cache import cache
from django.db import connection

from apps.core.choices import OutboxStatus
from apps.core.models import OutboxMessage


def check_database() -> tuple[bool, str]:
    """بررسی اتصال زنده به پایگاه‌دادهٔ اصلی با یک پرس‌وجوی سبک."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
        return (row is not None and int(row[0]) == 1), "ok"
    except Exception as exc:  # pragma: no cover
        return False, str(exc)[:200]


def check_cache() -> tuple[bool, str]:
    """بررسی صحت چرخهٔ نوشتن و خواندن در انبار کش."""
    probe_key = "health:probe"
    try:
        cache.set(probe_key, "alive", timeout=10)
        val = cache.get(probe_key)
        return val == "alive", "ok" if val == "alive" else "mismatch"
    except Exception as exc:  # pragma: no cover
        return False, str(exc)[:200]


def build_detailed_health(*, include_audit: bool = True) -> tuple[bool, dict[str, Any]]:
    """تولید گزارش جامع سلامت عملیاتی شامل دیتابیس، کش، صندوق خروجی و زنجیرهٔ حسابرسی."""
    db_ok, db_detail = check_database()
    cache_ok, cache_detail = check_cache()
    dead_outbox = OutboxMessage.objects.filter(status=OutboxStatus.DEAD).count() if db_ok else -1
    pending_outbox = (
        OutboxMessage.objects.filter(status=OutboxStatus.PENDING).count() if db_ok else -1
    )

    audit_ok = True
    if include_audit and db_ok:
        from apps.audit.services import verify_chain

        audit_ok, _ = verify_chain(limit=200)

    overall_ok = db_ok and cache_ok and audit_ok and dead_outbox == 0
    report: dict[str, Any] = {
        "status": "healthy" if overall_ok else ("degraded" if db_ok else "unhealthy"),
        "checks": {
            "database": {"ok": db_ok, "detail": db_detail},
            "cache": {"ok": cache_ok, "detail": cache_detail},
            "audit_chain": {"ok": audit_ok},
            "outbox": {"pending": pending_outbox, "dead": dead_outbox},
        },
    }
    return overall_ok, report
