"""فرمان راستی‌آزمایی روزانهٔ زنجیره ممیزی، صدور AuditAnchor و کنترل تراز دفترکل."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.audit.models import AuditRecord
from apps.audit.services import create_audit_anchor, verify_chain
from apps.ledger.services import capture_financial_control_snapshot


class Command(BaseCommand):
    """راستی‌آزمایی کامل زنجیره هش ممیزی و تراز آزمایشی دفترکل دوطرفه."""

    help = "بررسی یکپارچگی زنجیره ممیزی SHA-256، ثبت لنگر امضاشده و کنترل تراز دفترکل"

    def handle(self, *args: Any, **options: Any) -> None:
        del args, options
        valid, broken_seq = verify_chain()
        if not valid:
            raise CommandError(f"Audit chain integrity failure at sequence={broken_seq}")

        anchor = create_audit_anchor() if AuditRecord.all_objects.exists() else None
        fin_snap = capture_financial_control_snapshot()
        if not fin_snap.is_balanced:
            raise CommandError(
                f"Ledger control snapshot unbalanced! drift={fin_snap.counter_drift_rial}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Integrity verified: anchor_created={anchor is not None} ledger_balanced={fin_snap.is_balanced}"
            )
        )
