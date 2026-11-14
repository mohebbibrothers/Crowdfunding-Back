"""محاسبهٔ تاریخ قسط‌های ماهانه — پرریسک‌ترین ریاضیات یک موتور پرداخت مستمر.

═══════════════════════════════════════════════════════════════════════════════
چرا این فایل جدا و این‌قدر مستند است؟

«ماه بعد» یک مفهوم سادهٔ انسانی است که در کد شکننده می‌شود:

    ۳۱ فروردین + ۱ ماه = ؟        اردیبهشت ۳۱ روز ندارد.
    ۲۹ اسفند در سال غیرکبیسه + ۱ ماه = ؟
    ۳۱ خرداد + ۳ ماه = ؟           شهریور ۳۱ روز دارد، ولی آذر نه.

اگر این منطق اشتباه باشد، نتیجه‌اش این است که خیر هر چند ماه یک بار
«قسطی که وجود ندارد» یا «دو قسط با تاریخ یکسان» می‌بیند — و اعتماد به
سامانه یک‌بار برای همیشه از بین می‌رود.

تصمیم‌های صریح این فایل (هر کدام یک انتخاب آگاهانه، نه پیش‌فرض زبان):

  ۱. **روز ناموجود ⇒ آخرین روز ماه.**
     شروع ۳۱ فروردین ⇒ اردیبهشت ۳۱ ندارد ⇒ ۳۱ اردیبهشت ← ۳۰ اردیبهشت.
     ولی **میخ روی روز اصلی** می‌ماند: خرداد باز ۳۱ است، نه ۳۰.
     اگر میخ را از دست می‌دادیم، خیرِ ۳۱‌ام برای همیشه به ۳۰‌ام می‌رفت.

  ۲. **هرگز عقب نمی‌رویم.** تاریخ بعدی همیشه اکیداً بزرگ‌تر از قبلی است.
     این ضمانت جلوی حلقهٔ بی‌پایان در کرون و «قسط تکراری» را می‌گیرد.

  ۳. **همه‌چیز در UTC، ولی «امروز» به وقت تهران.**
     سررسید یک مفهوم تقویمی انسانی است، نه لحظه‌ای فیزیکی. اگر ساعت ۰۰:۳۰
     تهران را UTC حساب کنیم، ۲۰:۳۰ روز قبل می‌شود و قسط یک روز زودتر
     ساخته می‌شود. پس: تصمیم‌گیری با تاریخ تهران، ذخیره‌سازی با UTC.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, time, timedelta
from typing import Final

from django.utils import timezone

# منطقهٔ زمانی عملیاتی ایران. عمداً ثابت است، نه از تنظیمات: سررسید قسط
# یک مفهوم تجاری ایرانی است و تغییر آن با تغییر TIME_ZONE سرور، باگ می‌سازد.
TEHRAN_OFFSET: Final = timedelta(hours=3, minutes=30)


def tehran_now() -> datetime:
    """زمان فعلی به وقت تهران (aware) — مبنای تمام تصمیم‌های تقویمی."""
    return timezone.now().astimezone(UTC) + TEHRAN_OFFSET


def tehran_today() -> date:
    """تاریخ امروز به وقت تهران.

    چرا ``date`` و نه ``datetime``؟
        «سررسید ۵ آذر» یک روز تقویمی است، نه یک لحظه. با ``date`` همه‌چیز
        دربارهٔ ساعت و منطقهٔ زمانی از معادله حذف می‌شود — کمترین سطح تماس
        با کدهای خطاپذیر.
    """
    return tehran_now().date()


def tehran_day_start_utc(day: date) -> datetime:
    """آغاز یک روز تهران، بیان‌شده به UTC — برای ذخیره در فیلدهای تاریخ‌زمانی."""
    naive_midnight = datetime.combine(day, time.min)
    return (naive_midnight - TEHRAN_OFFSET).replace(tzinfo=UTC)


def _clamp_day(year: int, month: int, anchor_day: int) -> date:
    """ساخت تاریخ با «میخ روز» و بریدن به آخرین روز ماه در صورت لزوم."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(anchor_day, last_day))


def add_months(anchor: date, months: int) -> date:
    """افزودن ماه تقویمی به یک تاریخ، با حفظ «میخ روز» تا حد امکان.

    >>> add_months(date(2026, 4, 21), 1)  # ۳۱ فروردین ⇒ اردیبهشت ۳۰ روزه
    datetime.date(2026, 5, 21)

    منطق: روزِ میخ (``anchor.day``) حفظ می‌شود مگر در ماهی که آن روز وجود
    ندارد؛ آن‌وقت آخرین روز ماه انتخاب می‌شود. ماه بعد دوباره میخ اصلی
    اعمال می‌شود — این تفاوت کلیدی با «همیشه به آخرین روز برو» است.
    """
    if months < 0:
        raise ValueError("add_months فقط برای ماه‌های نامنفی است.")

    total = (anchor.year * 12 + (anchor.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    return _clamp_day(year, month, anchor.day)


def next_occurrence(
    *,
    anchor_day: int,
    after: date,
    interval_months: int,
) -> date:
    """نخستین تاریخ قسط **پس از** ``after`` با میخ روز مشخص.

    این تابع تضمین می‌کند خروجی همیشه اکیداً بزرگ‌تر از ``after`` باشد.

    نکتهٔ ظریف: ``after`` اکیداً است، نه «بزرگ‌تر یا مساوی». یعنی اگر خودِ
    امروز روز میخ باشد، نتیجه **ماه بعد** است — چون قسط امروز پیش‌تر ساخته
    شده و تکرارش یعنی دو بار کسر از حساب خیر.

    >>> from datetime import date
    >>> next_occurrence(anchor_day=21, after=date(2026, 4, 20), interval_months=1)
    datetime.date(2026, 4, 21)
    >>> next_occurrence(anchor_day=21, after=date(2026, 4, 21), interval_months=1)
    datetime.date(2026, 5, 21)
    >>> next_occurrence(anchor_day=31, after=date(2026, 4, 30), interval_months=1)
    datetime.date(2026, 5, 31)
    >>> next_occurrence(anchor_day=31, after=date(2026, 3, 1), interval_months=1)
    datetime.date(2026, 3, 31)
    >>> next_occurrence(anchor_day=15, after=date(2026, 1, 16), interval_months=3)
    datetime.date(2026, 4, 15)
    """
    if not 1 <= anchor_day <= 31:
        raise ValueError("anchor_day باید بین ۱ تا ۳۱ باشد.")
    if interval_months < 1:
        raise ValueError("interval_months باید حداقل ۱ باشد.")

    # از ماه جاری شروع می‌کنیم (offset = 0) — پرش از ماه جاری یعنی قسط این
    # ماه هرگز ساخته نمی‌شود و خیر یک ماه کامل را از دست می‌دهد.
    current = date(after.year, after.month, 1)
    for step in range(0, 400):
        offset = step * interval_months
        candidate_month = add_months(current, offset)
        candidate = _clamp_day(candidate_month.year, candidate_month.month, anchor_day)
        if candidate > after:
            return candidate
    # دفاعی: با ماه‌های ۱ تا ۱۲ و ۴۰۰ تلاش، هرگز به اینجا نمی‌رسیم.
    raise AssertionError("محاسبهٔ تاریخ قسط به نتیجه نرسید — ورودی نامعتبر است.")


def advance_due_date(
    *,
    current_due: date,
    anchor_day: int,
    interval_months: int,
    from_date: date | None = None,
) -> date:
    """محاسبهٔ سررسید بعدی از سررسید فعلی — با ضمانت «هرگز عقب نرو».

    ``from_date`` اختیاری است: اگر ساعت سیستم عقب رفته باشد و از سررسید
    فعلی محاسبه کنیم، ممکن است تاریخی در گذشته بسازیم که بلافاصله دوباره
    سررسید شود. با دادن ``from_date`` (معمولاً امروز)، نتیجه همیشه در
    آیندهٔ نسبت به آن خواهد بود.
    """
    reference = from_date if from_date is not None else current_due
    nxt = next_occurrence(
        anchor_day=anchor_day, after=max(current_due, reference), interval_months=interval_months
    )
    if nxt <= current_due:  # pragma: no cover - دفاعی
        raise AssertionError("سررسید بعدی نمی‌تواند کوچک‌تر یا مساوی فعلی باشد.")
    return nxt


def is_within_reminder_window(*, hour: int, start_hour: int, end_hour: int) -> bool:
    """آیا ساعت داده‌شده در پنجرهٔ مجاز ارسال یادآوری است؟

    پنجرهٔ محترمانه: پیامک ساعت ۳ بامداد یعنی اپلیکیشن اخراج‌شده. این جزئیات
    کوچک، تفاوت بین «ابزار مفید» و «مزاحم» است.

    از دو مقایسهٔ ساده استفاده می‌کنیم، نه چرخش مدولار — چون پنجرهٔ ۹ تا ۲۱
    هیچ‌گاه از نیمه‌شب عبور نمی‌کند و پشتیبانی از پنجرهٔ شبانه، پیچیدگی بی‌فایده
    به یک منطق امنیتی-تجاری اضافه می‌کند.
    """
    return start_hour <= hour < end_hour


def months_between(earlier: date, later: date) -> int:
    """تعداد ماه کامل بین دو تاریخ — برای محاسبهٔ عمر تعهد در آمار ریزش."""
    if later < earlier:
        return 0
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)
