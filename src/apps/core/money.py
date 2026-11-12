"""محاسبات دقیق پولی — ریال به‌عنوان منبع حقیقت دفتر کل و نمای دوگانهٔ ریال/تومان.

قواعد آهنین مالی:
    ۱. استفاده از float در کل پروژه برای مبالغ پولی مطلقاً ممنوع است؛ فقط int صحیح.
    ۲. تمامی ستون‌های دیتابیس و اسناد دفتر کل دوطرفه بر پایهٔ ریال (IRR) ذخیره می‌شوند
       تا با درگاه‌های شاپرک و گزارش‌های تسویهٔ بانکی هیچ خطای ضریب ۱۰ رخ ندهد.
    ۳. در خروجی‌های API، هم مقدار ریالی و هم معادل تومانی (تقسیم صحیح بر ۱۰) ارائه می‌شود.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

RIALS_PER_TOMAN: Final[int] = 10


@dataclass(frozen=True, slots=True)
class MoneyPair:
    """نمای تغییرناپذیر یک مبلغ در دو واحد ریال و تومان."""

    rial: int

    def __post_init__(self) -> None:
        if isinstance(self.rial, bool) or not isinstance(self.rial, int):
            msg = "مبلغ ریالی باید عدد صحیح (int) باشد."
            raise TypeError(msg)

    @property
    def toman(self) -> int:
        """معادل تومانی مبلغ (تقسیم صحیح بر ۱۰)."""
        return rial_to_toman(self.rial)

    def as_dict(self) -> dict[str, int]:
        """تبدیل به دیکشنری استاندارد قرارداد API."""
        return {"rial": self.rial, "toman": self.toman}


def rial_to_toman(amount_rial: int) -> int:
    """تبدیل عدد صحیح ریال به تومان (با حفظ علامت برای اسناد اصلاحی)."""
    if amount_rial < 0:
        return -((-amount_rial) // RIALS_PER_TOMAN)
    return amount_rial // RIALS_PER_TOMAN


def toman_to_rial(amount_toman: int) -> int:
    """تبدیل عدد صحیح تومان به ریال."""
    return int(amount_toman) * RIALS_PER_TOMAN


def assert_positive_rial(amount_rial: int, *, divisible_by_toman: bool = True) -> int:
    """اعتبارسنجی مبلغ مثبت ریالی و مضرب ۱۰ بودن آن در صورت نیاز."""
    if isinstance(amount_rial, bool) or not isinstance(amount_rial, int) or amount_rial <= 0:
        msg = "مبلغ باید یک عدد صحیح مثبت به ریال باشد."
        raise ValueError(msg)
    if divisible_by_toman and amount_rial % RIALS_PER_TOMAN != 0:
        msg = "مبلغ ریالی باید مضرب ۱۰ (معادل دقیق تومان) باشد."
        raise ValueError(msg)
    return amount_rial


def money_fields(prefix: str, amount_rial: int) -> dict[str, Any]:
    """تولید جفت کلیدهای ``{prefix}_rial`` و ``{prefix}_toman`` برای پاسخ‌های API."""
    return {
        f"{prefix}_rial": int(amount_rial),
        f"{prefix}_toman": rial_to_toman(int(amount_rial)),
    }
