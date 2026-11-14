"""ارسال تعهدهای بازپرداخت به درگاه — فرمان کرون تکمیل حلقهٔ وجه."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.contributions.services import dispatch_pending_refunds


class Command(BaseCommand):
    """ارسال دسته‌ای تعهدهای بازپرداخت معلق به درگاه پرداخت."""

    help = "ارسال تعهدهای بازپرداخت PENDING به درگاه و ثبت نتیجهٔ هر تلاش"

    def add_arguments(self, parser: CommandParser) -> None:
        """تعریف گزینه‌های خط فرمان."""
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="حداکثر تعداد بازپرداخت ارسالی در این اجرا (پیش‌فرض: ۱۰۰)",
        )
        parser.add_argument("--json", action="store_true", help="چاپ خروجی JSON برای پایش خودکار")

    def handle(self, *args: Any, **options: Any) -> None:
        """اجرای ارسال و چاپ گزارش."""
        del args
        stats = dispatch_pending_refunds(batch_size=int(options["batch_size"]))
        if bool(options["json"]):
            import json

            self.stdout.write(json.dumps(stats, ensure_ascii=False))
            return

        if stats["skipped"] == -1:
            self.stdout.write(
                self.style.WARNING(
                    "ارسال خودکار بازپرداخت در سیاست‌های سامانه غیرفعال است "
                    "(recovery.auto_refund_enabled=false)."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"تلاش={stats['attempted']} · ارسال‌شده={stats['sent']} · "
                f"نیازمند اقدام دستی={stats['manual']} · خطا={stats['failed']}"
            )
        )
