"""داوری خودکار پرداخت‌های رهاشده — فرمان کرون حلقهٔ نجات وجه.

نمونهٔ زمان‌بندی (``deploy/cpanel/cron_jobs.sh``):
    */5 * * * *  manage.py reconcile_abandoned_payments --batch-size 200
    */10 * * * * manage.py dispatch_pending_refunds --batch-size 100

این فرمان idempotent است: اجرای مکرر باعث دوباره‌تخصیص سهم یا دوباره‌بازپرداخت
نمی‌شود، چون هر پرداخت پیش از داوری با ``select_for_update`` قفل و وجود
``LateCaptureRecovery`` حل‌شده بررسی می‌شود.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.contributions.services import reconcile_abandoned_payments


class Command(BaseCommand):
    """داوری دسته‌ای پرداخت‌های رهاشده با استعلام مستقیم از درگاه."""

    help = "استعلام پرداخت‌های رهاشده از درگاه و تخصیص دوبارهٔ سهم یا ثبت تعهد بازپرداخت"

    def add_arguments(self, parser: CommandParser) -> None:
        """تعریف گزینه‌های خط فرمان فرمان داوری."""
        parser.add_argument(
            "--batch-size",
            type=int,
            default=200,
            help="حداکثر تعداد پرداخت داوری‌شده در این اجرا (پیش‌فرض: ۲۰۰)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="فقط شمارش و فهرست نامزدها، بدون هیچ تغییری در داده",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="چاپ خروجی به فرمت JSON برای مصرف در پایش خودکار",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """اجرای داوری و چاپ گزارش فارسی/JSON."""
        del args
        stats = reconcile_abandoned_payments(
            batch_size=int(options["batch_size"]),
            dry_run=bool(options["dry_run"]),
        )
        if bool(options["json"]):
            import json

            self.stdout.write(json.dumps(stats, ensure_ascii=False))
            return

        label = "پیش‌نمایش (بدون تغییر)" if stats["dry_run"] else "داوری انجام‌شده"
        self.stdout.write(
            self.style.SUCCESS(
                f"[{label}] بررسی‌شده={stats['scanned']} · "
                f"پولی نبود={stats['not_captured']} · "
                f"بازیافت‌شده={stats['recovered']} · "
                f"بازپرداخت لازم={stats['refund_pending']} · "
                f"نیازمند بررسی انسانی={stats['manual_review']} · "
                f"خطا={stats['error_count']}"
            )
        )
        if stats["dry_run"] and stats.get("candidate_ids"):
            self.stdout.write("نامزدها: " + ", ".join(stats["candidate_ids"]))
