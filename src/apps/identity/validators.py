"""اعتبارسنجی و نرمال‌سازی شماره تلفن، کد ملی ایران و شبای بانکی."""

from __future__ import annotations

import re

from apps.core.errors import ValidationError as DomainValidationError
from apps.core.jalali import normalize_digits

_IRAN_MOBILE_RE = re.compile(r"^09\d{9}$")
_INTL_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
_NATIONAL_CODE_RE = re.compile(r"^\d{10}$")
_IBAN_RE = re.compile(r"^IR\d{24}$")


def normalize_phone(raw: str) -> str:
    """نرمال‌سازی شماره موبایل به قالب استاندارد ``09xxxxxxxxx`` (ایران) یا ``+E.164``."""
    cleaned = normalize_digits(raw or "").strip().replace(" ", "").replace("-", "")
    if cleaned.startswith("+989") and len(cleaned) == 13:
        cleaned = "0" + cleaned[3:]
    elif cleaned.startswith("00989") and len(cleaned) == 14:
        cleaned = "0" + cleaned[4:]
    elif cleaned.startswith("989") and len(cleaned) == 12:
        cleaned = "0" + cleaned[2:]
    elif len(cleaned) == 10 and cleaned.startswith("9") and cleaned.isdigit():
        cleaned = "0" + cleaned

    if _IRAN_MOBILE_RE.match(cleaned) or _INTL_E164_RE.match(cleaned):
        return cleaned
    raise DomainValidationError(
        "شماره موبایل واردشده معتبر نیست (نمونهٔ صحیح: 09123456789).",
        code="invalid_phone",
        errors={"phone": ["شماره موبایل معتبر ۱۱ رقمی وارد کنید."]},
    )


def validate_iranian_national_code(raw: str) -> str:
    """اعتبارسنجی رقم کنترلی کد ملی ۱۰ رقمی جمهوری اسلامی ایران."""
    cleaned = normalize_digits(raw or "").strip()
    if not _NATIONAL_CODE_RE.match(cleaned) or len(set(cleaned)) == 1:
        raise DomainValidationError(
            "کد ملی واردشده معتبر نیست.",
            code="invalid_national_code",
            errors={"national_code": ["کد ملی ۱۰ رقمی معتبر وارد کنید."]},
        )
    checksum = sum(int(cleaned[i]) * (10 - i) for i in range(9))
    remainder = checksum % 11
    control = int(cleaned[9])
    valid = (remainder < 2 and control == remainder) or (
        remainder >= 2 and control == 11 - remainder
    )
    if not valid:
        raise DomainValidationError(
            "رقم کنترلی کد ملی نادرست است.",
            code="invalid_national_code",
            errors={"national_code": ["کد ملی واردشده معتبر نیست."]},
        )
    return cleaned


def validate_iranian_iban(raw: str) -> str:
    """اعتبارسنجی شماره شبای ۲۶ کاراکتری ایران بر پایهٔ الگوریتم استاندارد ISO 7064 Mod 97-10."""
    cleaned = normalize_digits(raw or "").strip().replace(" ", "").upper()
    if not _IBAN_RE.match(cleaned):
        raise DomainValidationError(
            "شماره شبا باید با IR شروع شده و ۲۶ کاراکتر باشد.",
            code="invalid_sheba",
            errors={"sheba": ["شماره شبای ۲۶ کاراکتری معتبر (IR...) وارد کنید."]},
        )
    rearranged = cleaned[4:] + "1827" + cleaned[2:4]
    if int(rearranged) % 97 != 1:
        raise DomainValidationError(
            "ارقام کنترلی شماره شبا معتبر نیست.",
            code="invalid_sheba",
            errors={"sheba": ["شماره شبای بانکی نامعتبر است."]},
        )
    return cleaned


def compute_iban_check_digits(bban_22_digits: str) -> str:
    """محاسبهٔ دو رقم کنترلی استاندارد ISO 7064 Mod 97-10 برای ۲۲ رقم پایهٔ شبای ایران."""
    cleaned = normalize_digits(bban_22_digits).strip()
    if len(cleaned) != 22 or not cleaned.isdigit():
        raise DomainValidationError("بخش پایه شماره شبای ایران باید دقیقاً ۲۲ رقم عددی باشد.")
    rem = int(cleaned + "182700") % 97
    return f"{98 - rem:02d}"
