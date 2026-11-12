"""فرمان تخلیهٔ صف صندوق خروجی تراکنشی (Transactional Outbox Worker — قابل اجرا با Cron)."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.core.outbox import drain_outbox


class Command(BaseCommand):
    """پردازش دسته‌ای پیام‌های آماده در جدول ``OutboxMessage``."""

    help = "پردازش پیام‌های در انتظار صندوق خروجی تراکنشی (پیامک‌ها و اعلان‌های سهام‌داران)"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args: Any, **options: Any) -> None:
        del args
        batch_size = int(options["batch_size"])
        stats = drain_outbox(batch_size=batch_size)
        self.stdout.write(
            self.style.SUCCESS(
                f"Outbox processed: delivered={stats['delivered']} failed={stats['failed']} dead={stats['dead']}"
            )
        )
