"""تبدیل دقیق تقویم میلادی و جلالی (شمسی) بدون وابستگی خارجی.

قرارداد ماشینی پروژه (ADR-0009):
    • تمامی رشته‌های تاریخ جلالی در پاسخ‌های JSON و خروجی‌های ماشینی با ارقام لاتین
      در قالب ``YYYY-MM-DD`` برگردانده می‌شوند (مثلاً ``1405-08-21``).
    • تبدیل به ارقام فارسی فقط در لایهٔ نمایش یا برگه‌های چاپی اکسل انجام می‌شود.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

_GREGORIAN_DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_JALALI_DAYS_IN_MONTH = (31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29)
_PERSIAN_DIGITS_MAP = str.maketrans(
    "0123456789٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "012345678901234567890123456789"
)
_TO_PERSIAN_MAP = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def normalize_digits(text: str) -> str:
    """تبدیل ارقام فارسی و عربی به ارقام لاتین استاندارد برای پردازش ورودی."""
    return text.translate(_PERSIAN_DIGITS_MAP)


def to_persian_digits(text: str) -> str:
    """تبدیل ارقام لاتین به فارسی برای متون نمایشی و چاپی."""
    return text.translate(_TO_PERSIAN_MAP)


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """الگوریتم استاندارد تبدیل تاریخ میلادی به (سال، ماه، روز) شمسی."""
    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1

    g_day_no = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    for i in range(gm2):
        g_day_no += _GREGORIAN_DAYS_IN_MONTH[i]
    if gm2 > 1 and ((gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)):
        g_day_no += 1
    g_day_no += gd2

    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053

    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461

    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365

    jm = 0
    for i in range(11):
        if j_day_no < _JALALI_DAYS_IN_MONTH[i]:
            jm = i + 1
            break
        j_day_no -= _JALALI_DAYS_IN_MONTH[i]
    else:
        jm = 12

    jd = j_day_no + 1
    return jy, jm, jd


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> date:
    """تبدیل تاریخ شمسی (سال، ماه، روز) به شیء ``datetime.date`` میلادی."""
    if not (1200 <= jy <= 1600 and 1 <= jm <= 12 and 1 <= jd <= 31):
        msg = f"تاریخ جلالی نامعتبر است: {jy:04d}-{jm:02d}-{jd:02d}"
        raise ValueError(msg)
    if jm > 6 and jd == 31:
        msg = "ماه‌های نیمهٔ دوم سال شمسی حداکثر ۳۰ روز هستند."
        raise ValueError(msg)

    jy2 = jy - 979
    jm2 = jm - 1
    jd2 = jd - 1

    j_day_no = 365 * jy2 + (jy2 // 33) * 8 + ((jy2 % 33 + 3) // 4)
    for i in range(jm2):
        j_day_no += _JALALI_DAYS_IN_MONTH[i]
    j_day_no += jd2

    g_day_no = j_day_no + 79
    gy = 1600 + 400 * (g_day_no // 146097)
    g_day_no %= 146097

    leap = True
    if g_day_no >= 36525:
        g_day_no -= 1
        gy += 100 * (g_day_no // 36524)
        g_day_no %= 36524
        if g_day_no >= 365:
            g_day_no += 1
        else:
            leap = False

    gy += 4 * (g_day_no // 1461)
    g_day_no %= 1461

    if g_day_no >= 366:
        leap = False
        g_day_no -= 1
        gy += g_day_no // 365
        g_day_no %= 365

    gm = 0
    for i in range(12):
        days = _GREGORIAN_DAYS_IN_MONTH[i] + (1 if (i == 1 and leap) else 0)
        if g_day_no < days:
            gm = i + 1
            break
        g_day_no -= days

    gd = g_day_no + 1
    result = date(gy, gm, gd)
    if gregorian_to_jalali(result.year, result.month, result.day) != (jy, jm, jd):
        msg = f"روز کبیسهٔ نامعتبر در تاریخ جلالی: {jy:04d}-{jm:02d}-{jd:02d}"
        raise ValueError(msg)
    return result


def format_jalali_date(value: date | datetime | None) -> str | None:
    """قالب‌بندی تاریخ یا زمان به رشتهٔ ``YYYY-MM-DD`` شمسی در منطقهٔ زمانی تهران."""
    if value is None:
        return None
    if isinstance(value, datetime):
        tz = ZoneInfo(getattr(settings, "TIME_ZONE", "Asia/Tehran"))
        aware = value if timezone.is_aware(value) else timezone.make_aware(value, tz)
        local_dt = aware.astimezone(tz)
        target = local_dt.date()
    else:
        target = value
    jy, jm, jd = gregorian_to_jalali(target.year, target.month, target.day)
    return f"{jy:04d}-{jm:02d}-{jd:02d}"


def format_jalali_datetime(value: datetime | None) -> str | None:
    """قالب‌بندی زمان به رشتهٔ ``YYYY-MM-DD HH:MM`` شمسی در منطقهٔ زمانی محلی."""
    if value is None:
        return None
    tz = ZoneInfo(getattr(settings, "TIME_ZONE", "Asia/Tehran"))
    aware = value if timezone.is_aware(value) else timezone.make_aware(value, tz)
    local_dt = aware.astimezone(tz)
    jy, jm, jd = gregorian_to_jalali(local_dt.year, local_dt.month, local_dt.day)
    return f"{jy:04d}-{jm:02d}-{jd:02d} {local_dt.hour:02d}:{local_dt.minute:02d}"


def today_jalali() -> str:
    """تاریخ امروز شمسی بر پایهٔ منطقهٔ زمانی سامانه."""
    return format_jalali_date(timezone.now()) or ""
