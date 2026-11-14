"""چرخهٔ تعهد کمک مستمر — فرمان کرون با چهار گام مستقل و قابل‌پایش.

═══════════════════════════════════════════════════════════════════════════════
چرا چهار گام جدا و نه یک فرمان «همه‌کار»؟

چون هر گام می‌تواند مستقل شکست بخورد و شکست یکی نباید بقیه را متوقف کند:

  ۱. **بازگشت از توقف** — تعهدهایی که دورهٔ توقفشان تمام شده.
  ۲. **تولید قسط** — قسط جدید برای سررسیدهای رسیده. باید حتی اگر پیامک
     ارسال نشود انجام شود؛ وگرنه خیر در پنلش چیزی برای پرداخت نمی‌بیند.
  ۳. **یادآوری** — فقط داخل پنجرهٔ محترمانه (۹ تا ۲۱ تهران) و با سقف.
  ۴. **انقضا** — قسط‌های معوق و تعهدهای دارای شکست متوالی.

تفکیک گام ۲ و ۳ مهم‌ترین تصمیم این فرمان است: خطای اپراتور پیامک هرگز
نباید تولید قسط را عقب بیندازد.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.contributions.recurring import (
    dispatch_pledge_reminders,
    expire_stale_installments,
    materialize_due_installments,
    resume_paused_pledges,
)


class Command(BaseCommand):
    """اجرای چرخهٔ کامل تعهد مستمر با گزارش JSON یا خوانا."""

    help = "چرخهٔ تعهد کمک مستمر: بازگشت از توقف، تولید قسط، یادآوری محترمانه، انقضا"

    def add_arguments(self, parser: CommandParser) -> None:
        """تعریف گزینه‌های خط فرمان."""
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="حداکثر تعهد/قسط پردازش‌شده در هر گام (پیش‌فرض: ۵۰۰)",
        )
        parser.add_argument(
            "--skip-reminders",
            action="store_true",
            help="تولید قسط و انقضا را انجام بده ولی هیچ پیامکی نفرست",
        )
        parser.add_argument(
            "--only",
            choices=["resume", "materialize", "remind", "expire"],
            default=None,
            help="اجرای تنها یک گام مشخص (برای عیب‌یابی)",
        )
        parser.add_argument("--json", action="store_true", help="چاپ خروجی JSON برای پایش خودکار")

    def handle(self, *args: Any, **options: Any) -> None:
        """اجرای گام‌ها به ترتیب و چاپ گزارش."""
        del args
        batch = max(1, int(options["batch_size"]))
        only = options["only"]
        skip_reminders = bool(options["skip_reminders"])

        report: dict[str, Any] = {}

        if only in (None, "resume"):
            report["resumed"] = resume_paused_pledges()
        if only in (None, "materialize"):
            report["materialize"] = materialize_due_installments(batch_size=batch).as_dict()
        if only in (None, "remind") and not skip_reminders:
            report["reminders"] = dispatch_pledge_reminders(batch_size=batch).as_dict()
        elif skip_reminders and only in (None, "remind"):
            report["reminders"] = {"skipped": "با --skip-reminders غیرفعال شد"}
        if only in (None, "expire"):
            report["expiry"] = expire_stale_installments().as_dict()

        if bool(options["json"]):
            self.stdout.write(json.dumps(report, ensure_ascii=False))
            return

        self.stdout.write(self.style.SUCCESS("چرخهٔ تعهد مستمر اجرا شد:"))
        for key, value in report.items():
            self.stdout.write(f"  • {key}: {value}")
