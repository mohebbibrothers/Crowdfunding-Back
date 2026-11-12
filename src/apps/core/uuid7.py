"""تولید شناسهٔ یکنوا UUIDv7 منطبق بر استاندارد RFC 9562.

چرا UUIDv7 به‌جای عدد ترتیبی یا UUIDv4؟
    ۱. مرتب‌بودن زمانی (۴۸ بیت میلی‌ثانیه در بایت‌های پرارزش) درج‌های ایندکس B-Tree
       در MariaDB/InnoDB را انتهایی و متراکم نگه می‌دارد (بدون صفحهٔ شکستهٔ تصادفی).
    ۲. غیرقابل‌حدس بودن ۶۲ بیت تصادفی، شمارش کاربران، حرکت‌ها و رسیدها را ناممکن می‌کند.
    ۳. شمارندهٔ ۱۲ بیتی یکنوا، ترتیب دقیق رکوردهای هم‌میلی‌ثانیه را درون یک فرآیند حفظ می‌کند.
"""

from __future__ import annotations

import os
import threading
import time
import uuid

_VERSION = 0x7
_VARIANT_RFC4122 = 0b10
_RAND_A_MAX = 0xFFF
_RESYNC_THRESHOLD_MS = 2_000
_LOCK = threading.Lock()
_last_ms: int = -1
_counter: int = 0


def _now_ms() -> int:
    """زمان فعلی یونیکس بر حسب میلی‌ثانیهٔ صحیح."""
    return int(time.time() * 1000)


def uuid7() -> uuid.UUID:
    """تولید یک UUIDv7 یکنوا و ایمن برای کلید اصلی جداول."""
    global _last_ms, _counter  # noqa: PLW0603

    with _LOCK:
        now_ms = _now_ms()
        if now_ms > _last_ms or (_last_ms - now_ms > _RESYNC_THRESHOLD_MS):
            _last_ms = now_ms
            _counter = int.from_bytes(os.urandom(2), "big") & _RAND_A_MAX
        else:
            now_ms = _last_ms
            _counter += 1
            if _counter > _RAND_A_MAX:
                _last_ms += 1
                now_ms = _last_ms
                _counter = 0

        rand_b = int.from_bytes(os.urandom(8), "big") >> 2
        value = (now_ms & 0xFFFFFFFFFFFF) << 80
        value |= _VERSION << 76
        value |= (_counter & _RAND_A_MAX) << 64
        value |= _VARIANT_RFC4122 << 62
        value |= rand_b
        return uuid.UUID(int=value)


def uuid7_hex() -> str:
    """نمایش ۳۲ کاراکتری بدون خط تیره برای کلیدها و شناسه‌های ردیابی."""
    return uuid7().hex


def uuid7_time_ms(value: uuid.UUID) -> int:
    """استخراج مهر زمان میلی‌ثانیه از یک شناسهٔ UUIDv7."""
    return value.int >> 80
