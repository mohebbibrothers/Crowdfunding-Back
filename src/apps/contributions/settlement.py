"""موتور تطبیق صورت‌حساب تسویهٔ درگاه با دفتر داخلی — «لایهٔ حقیقت وجه».

═══════════════════════════════════════════════════════════════════════════════
چرا این ماژول جدا از ``services.py`` است؟
    ``services.py`` حدود ۲۳۰۰ خط است و قلب چرخهٔ پرداخت. منطق تطبیق، دامنهٔ
    مسئولیت متفاوتی دارد: «کشف تناقض» در برابر «اجرای تراکنش». قاطی‌کردنشان
    یعنی هر تغییر در قالب فایل بانک، ریسک بازنویسی موتور پرداخت را دارد.

قاعدهٔ طلایی این ماژول:
    **تطبیق هرگز خودش پول جابه‌جا نمی‌کند.**
    فقط تشخیص می‌دهد و اقدام تجویز می‌کند. اقدام فقط از دو مسیر مجاز است:
      (الف) خوددرمانی امن برای حالت‌های بی‌ابهام — با همان موتور داوری موجود
      (ب) صف بررسی انسانی برای هر چیز دیگر
    «یک حقیقت، یک موتور»: مسیر موازی تازه‌ای برای تأیید پرداخت ساخته نمی‌شود.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from typing import Any

from django.db import transaction

from apps.contributions.choices import (
    LateCaptureOutcome,
    PaymentStatus,
    PaymentTruthState,
    SettlementRemediation,
    SettlementRowMatchStatus,
    SettlementStatementStatus,
)
from apps.contributions.models import (
    Payment,
    SettlementReconciliation,
    SettlementRow,
    SettlementStatement,
)
from apps.core.errors import NotFoundError, ValidationError as DomainValidationError
from apps.core.policy import get_policy

# ══════════════════════════════════════════════════════════════════════════════
# نرمال‌سازی — جایی که بیشتر باگ‌های واقعی تطبیق متولد می‌شوند
# ══════════════════════════════════════════════════════════════════════════════

# نویسه‌های فارسی/عربی که در فایل‌های اکسل ایران به‌وفور جایگزین رقم لاتین می‌شوند.
_DIGIT_TRANSLATION = str.maketrans(
    {
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
    }
)

# جداکننده‌های هزارگان که در صادرات اکسل ایران رایج‌اند.
_THOUSANDS_SEPARATORS = str.maketrans(
    {",": "", "٬": "", "،": "", " ": "", "\u200c": "", "\xa0": ""}
)


def normalize_amount_rial(raw: Any) -> int:
    """تبدیل هر نمایش مبلغ فایل به عدد صحیح ریال — یا رد صریح.

    سه دام واقعی که این تابع می‌گیرد:
      ۱) ارقام فارسی «۱٬۲۵۰٬۰۰۰» ⇒ 1250000
      ۲) اعشار «1250000.75» ⇒ **رد** (ریال عدد صحیح است؛ گردکردن در مسیر پول = گم‌شدن وجه)
      ۳) خالی/«-»/None ⇒ 0 (ردیف بی‌مبلغ در فایل تسویه رخداد عادی است)

    چرا گردکردن ممنوع است:
        اگر مرورگر/اکسل مبلغ را با گردکردن ذخیره کرده باشد، پذیرش آن یعنی ما
        ریالی را که وجود ندارد ثبت می‌کنیم. یک ریال اختلاف در یک تراکنش، در
        هزار تراکنش یعنی هزار ریال اختلاف دفتری که هیچ‌کس نمی‌داند از کجاست.
    """
    if raw is None:
        return 0
    if isinstance(raw, bool):  # bool زیرنوع int است؛ عمداً رد می‌کنیم
        raise DomainValidationError(
            "مبلغ نمی‌تواند مقدار منطقی باشد.", code="settlement_invalid_amount"
        )
    if isinstance(raw, int):
        if raw < 0:
            raise DomainValidationError(
                "مبلغ ردیف صورت‌حساب نمی‌تواند منفی باشد.", code="settlement_invalid_amount"
            )
        return raw
    if isinstance(raw, Decimal):
        if raw != raw.to_integral_value():
            raise DomainValidationError(
                f"مبلغ اعشاری «{raw}» در صورت‌حساب ریالی پذیرفته نیست؛ ریال عدد صحیح است.",
                code="settlement_fractional_amount",
            )
        return int(raw)

    text = str(raw).strip().translate(_DIGIT_TRANSLATION)
    if not text or text in {"-", "—", "–", "خالی", "None", "null", "N/A"}:
        return 0
    text = text.translate(_THOUSANDS_SEPARATORS)
    text = text.removeprefix("+")
    if text.startswith("-"):
        raise DomainValidationError(
            "مبلغ ردیف صورت‌حساب نمی‌تواند منفی باشد.", code="settlement_invalid_amount"
        )
    # «1250000.00» یعنی اکسل عدد را به‌شکل اعشار ذخیره کرده، ولی مقدار صحیح است.
    if "." in text:
        int_part, _, frac_part = text.partition(".")
        if frac_part.strip("0"):
            raise DomainValidationError(
                f"مبلغ اعشاری «{text}» در صورت‌حساب ریالی پذیرفته نیست؛ ریال عدد صحیح است.",
                code="settlement_fractional_amount",
            )
        text = int_part or "0"
    if not text.isdigit():
        raise DomainValidationError(
            f"مبلغ «{raw}» قابل تفسیر به عدد ریال نیست.", code="settlement_invalid_amount"
        )
    return int(text)


_PERSIAN_MONTHS = {
    "فروردین": 1,
    "اردیبهشت": 2,
    "خرداد": 3,
    "تیر": 4,
    "مرداد": 5,
    "شهریور": 6,
    "مهر": 7,
    "آبان": 8,
    "آذر": 9,
    "دی": 10,
    "بهمن": 11,
    "اسفند": 12,
}


def normalize_datetime(raw: Any) -> datetime | None:
    """تفسیر تاریخ فایل تسویه در چند قالب رایج ایران — یا ``None``.

    تاریخ در صورتحساب «تزیینی» نیست: بازهٔ پوشش سند مستقیماً از آن ساخته
    می‌شود و اشتباه‌خواندنش می‌تواند یک روز کامل تراکنش را بیرون از دامنهٔ
    تطبیق بیندازد. پس هر قالبی که مطمئن نیستیم، صریحاً ``None`` می‌شود و
    فراخوان تصمیم می‌گیرد — نه حدس.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)

    text = str(raw).strip().translate(_DIGIT_TRANSLATION)
    if not text:
        return None

    # ISO 8601 (رایج‌ترین قالب API و اکسل مدرن)
    iso_candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_candidate)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        pass

    # YYYY/MM/DD و YYYY-MM-DD با/بدون زمان
    for sep in ("/", "-"):
        parts = text.split()
        date_part, _, time_part = parts[0].partition("T")[0].partition(" ")
        chunks = date_part.replace(sep, "-").split("-") if sep == "/" else date_part.split("-")
        if len(chunks) == 3 and all(c.isdigit() for c in chunks):
            year, month, day = (int(c) for c in chunks)
            if year < 1000:  # «۱۴۰۵/۰۸/۲۲» بعد از تبدیل ارقام هم شمسی می‌ماند
                continue
            hour = minute = second = 0
            if time_part:
                t_chunks = time_part.replace(":", " ").split()
                if len(t_chunks) >= 2 and all(c.isdigit() for c in t_chunks[:3]):
                    hour, minute = int(t_chunks[0]), int(t_chunks[1])
                    second = int(t_chunks[2]) if len(t_chunks) > 2 else 0
            try:
                return datetime(year, month, day, hour, minute, second, tzinfo=UTC)
            except ValueError:
                continue
        break

    return None


def normalize_authority(raw: Any) -> str:
    """یکسان‌سازی شناسهٔ Authority: حذف فاصله، حروف بزرگ، حذف صفر بایت.

    تفاوت ``A1b2c3`` و `` A1B2C3`` در نگاه بشر یکی است، در نگاه ``unique`` دو
    تراکنش. اگر یک فایل با حروف بزرگ و پرداخت داخلی با حروف کوچک ثبت شده باشد،
    تطبیق شکست می‌خورد و پول «بی‌مالک» گزارش می‌شود — هشدار دروغ که اعتماد به
    کل سامانه را از بین می‌برد.
    """
    return str(raw or "").replace("\x00", "").strip().upper()


# ══════════════════════════════════════════════════════════════════════════════
# ساختار ردیف ورودی
# ══════════════════════════════════════════════════════════════════════════════

# نام‌های ستونی که در صادرات‌های واقعی بانک/درگاه دیده می‌شوند.
_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "authority": (
        "authority",
        "Authority",
        "کد_تراکنش",
        "شناسه_تراکنش",
        "شناسه تراکنش",
        "کد تراکنش",
        "authority_code",
    ),
    "ref_id": ("ref_id", "refid", "reference", "شماره_پیگیری", "شماره پیگیری", "کد_پیگیری"),
    "amount_rial": (
        "amount",
        "amount_rial",
        "مبلغ",
        "مبلغ_ریال",
        "مبلغ ریال",
        "مبلغ(ریال)",
        "مبلغ (ریال)",
        "price",
    ),
    "occurred_at": ("date", "created_at", "تاریخ", "زمان", "تاریخ_تراکنش", "تاریخ تراکنش"),
    "card_pan_masked": ("card_pan", "card", "شماره_کارت", "شماره کارت", "pan"),
    "description": ("description", "desc", "توضیحات", "شرح", "بابت"),
}


def _pick(row: Mapping[str, Any], canonical: str) -> Any:
    """انتخاب مقدار یک فیلد از ردیف خام با پذیرش نام‌های ستونی رایج."""
    for alias in _HEADER_ALIASES.get(canonical, (canonical,)):
        if alias in row:
            return row[alias]
    return None


@dataclass(frozen=True, slots=True)
class ParsedSettlementRow:
    """ردیف صورت‌حساب پس از نرمال‌سازی و اعتبارسنجی."""

    row_number: int
    authority: str
    ref_id: str
    amount_rial: int
    occurred_at: datetime | None
    card_pan_masked: str
    description: str
    raw_payload: dict[str, Any]
    error: str = ""

    @property
    def is_valid(self) -> bool:
        return not self.error


@dataclass(slots=True)
class ParseOutcome:
    """نتیجهٔ پارس مجموعه‌ای از ردیف‌ها."""

    rows: list[ParsedSettlementRow] = field(default_factory=list)
    rejected: list[ParsedSettlementRow] = field(default_factory=list)

    @property
    def computed_total_rial(self) -> int:
        return sum(r.amount_rial for r in self.rows if r.is_valid)


def _require_authority(raw: Any) -> str:
    """اجبار وجود شناسهٔ Authority در یک ردیف صورت‌حساب.

    ردیف بدون شناسه، قابل تطبیق نیست. اگر بی‌صدا رد شود، در شمارش کل سند
    «موفق» به‌نظر می‌رسد در حالی که یک تراکنش هرگز بررسی نشده — و همین
    «موفقیت دروغ» است که کل ارزش حسابرسی را از بین می‌برد.
    """
    authority = normalize_authority(raw)
    if not authority:
        raise DomainValidationError(
            "ردیف صورت‌حساب شناسهٔ Authority ندارد.", code="settlement_missing_authority"
        )
    return authority


def parse_settlement_rows(raw_rows: Iterable[Mapping[str, Any]]) -> ParseOutcome:
    """تبدیل ردیف‌های خام فایل به ``ParsedSettlementRow`` با رد صریح ردیف معیوب.

    تصمیم مهم: یک ردیف معیوب **کل سند را رد نمی‌کند**. فایل‌های واقعی همیشه
    یک سطر جمع یا یک ردیف خالی دارند. اگر کل سند را برای یک سطر بد رد کنیم،
    اپراتور دستش بسته می‌شود؛ اگر آن سطر را بی‌صدا بپذیریم، عددها دروغ می‌شوند.
    راه سوم: بپذیریم، ولی صریحاً در ``rejected`` گزارش کنیم تا انسان ببیند.
    """
    outcome = ParseOutcome()
    for index, raw in enumerate(raw_rows, start=1):
        payload = dict(raw)
        try:
            authority = _require_authority(_pick(payload, "authority"))
            amount = normalize_amount_rial(_pick(payload, "amount_rial"))
            row = ParsedSettlementRow(
                row_number=index,
                authority=authority,
                ref_id=str(_pick(payload, "ref_id") or "").strip()[:80],
                amount_rial=amount,
                occurred_at=normalize_datetime(_pick(payload, "occurred_at")),
                card_pan_masked=str(_pick(payload, "card_pan_masked") or "").strip()[:32],
                description=str(_pick(payload, "description") or "").strip()[:300],
                raw_payload=payload,
            )
            outcome.rows.append(row)
        except DomainValidationError as exc:
            outcome.rejected.append(
                ParsedSettlementRow(
                    row_number=index,
                    authority="",
                    ref_id="",
                    amount_rial=0,
                    occurred_at=None,
                    card_pan_masked="",
                    description="",
                    raw_payload=payload,
                    error=str(exc),
                )
            )
    return outcome


def compute_statement_fingerprint(
    *,
    gateway_name: str,
    period_start: datetime,
    period_end: datetime,
    rows: Sequence[Mapping[str, Any]],
) -> str:
    """اثر انگشت SHA-256 محتوای سند برای تضمین idempotency ورود.

    چرا ``period`` و ``gateway`` هم داخل هش می‌روند؟
        اگر فقط ردیف‌ها هش شوند، دو درگاه با ردیف یکسان (مثلاً Sandbox در دو
        محیط) یک سند تلقی می‌شوند. ورود بازه + درگاه، هش را به «این سند از این
        درگاه برای این بازه» تبدیل می‌کند — که دقیقاً همان چیزی است که یکتایی
        باید دربارهٔ آن باشد.

    ⚠️ قرارداد فراخوان: بازه باید از **خود فایل/صورت‌حساب** بیاید، نه از
    ``timezone.now()``. اگر فراخوان بازه را از ساعت دیوار بسازد، هر آپلودِ
    همان فایل بازهٔ متفاوتی دارد و idempotency به‌طور مصنوعی می‌شکند.
    """
    canonical = json.dumps(
        {
            "gateway": gateway_name,
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
            "rows": [
                {
                    "authority": normalize_authority(_pick(r, "authority")),
                    "amount": normalize_amount_rial(_pick(r, "amount_rial")),
                }
                for r in rows
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════
# سیاست‌های لایهٔ حقیقت
# ══════════════════════════════════════════════════════════════════════════════


# رجیستری پورت موتور داوری — توسط ``contributions.apps`` در زمان بارگذاری ثبت می‌شود.
_RECOVERY_ENGINE: Callable[..., Any] | None = None


def register_recovery_engine(engine: Callable[..., Any]) -> None:
    """ثبت موتور داوری موجود تا لایهٔ حقیقت بدون import چرخه‌ای از آن استفاده کند."""
    global _RECOVERY_ENGINE  # noqa: PLW0603
    _RECOVERY_ENGINE = engine


def _truth_policy() -> dict[str, Any]:
    """خواندن پارامترهای عملیاتی لایهٔ حقیقت از سیاست‌های پویا."""
    return {
        "max_statement_age_hours": int(get_policy("truth.max_statement_age_hours")),
        "auto_heal_enabled": bool(get_policy("truth.auto_heal_enabled")),
        "auto_heal_max_rial": int(get_policy("truth.auto_heal_max_rial")),
        "unresolved_impact_alert_rial": int(get_policy("truth.unresolved_impact_alert_rial")),
    }


# ══════════════════════════════════════════════════════════════════════════════
# ۱) ورود سند صورت‌حساب
# ══════════════════════════════════════════════════════════════════════════════


@transaction.atomic
def ingest_settlement_statement(
    *,
    gateway_name: str,
    source_kind: str,
    period_start: datetime,
    period_end: datetime,
    raw_rows: Sequence[Mapping[str, Any]],
    actor: Any = None,
    original_filename: str = "",
    declared_total_rial: int | None = None,
    statement_metadata: Mapping[str, Any] | None = None,
) -> tuple[SettlementStatement, ParseOutcome, bool]:
    """ورود یک صورت‌حساب تسویه — idempotent بر پایه اثر انگشت محتوا.

    خروجی ``(statement, parse_outcome, was_created)``:
        ``was_created=False`` یعنی همین سند قبلاً وارد شده و ما فقط آن را
        برگرداندیم؛ ردیف‌های تازه ساخته نشدند و هیچ چیز دوباره شمرده نمی‌شود.

    چرا ورود و تطبیق **دو گام جدا** هستند؟
        ورود باید بی‌طرف باشد: فقط داده را ثبت می‌کند. اگر ورود وابسته به
        نتیجهٔ تطبیق باشد، نمی‌توانیم منطق تطبیق را تغییر بدهیم و گذشته را
        دوباره بخوانیم — چون گذشته در لحظهٔ ورود محصول منطق آن روز بوده.
        جدا بودن این دو، همان چیزی است که «بازپردازش با منطق امروز» را ممکن می‌کند.
    """
    if period_end < period_start:
        raise DomainValidationError(
            "پایان بازهٔ صورت‌حساب نمی‌تواند پیش از شروع آن باشد.",
            code="settlement_invalid_period",
        )

    fingerprint = compute_statement_fingerprint(
        gateway_name=gateway_name,
        period_start=period_start,
        period_end=period_end,
        rows=raw_rows,
    )

    existing = SettlementStatement.objects.filter(
        gateway_name=gateway_name, statement_sha256=fingerprint
    ).first()
    if existing is not None:
        # ورود دوبارهی همان فایل: همان سند برمی‌گردد، نه سند دوم.
        return existing, ParseOutcome(), False

    parse = parse_settlement_rows(raw_rows)
    computed_total = parse.computed_total_rial

    integrity_ok = True
    integrity_note = ""
    if declared_total_rial is not None and int(declared_total_rial) != computed_total:
        integrity_ok = False
        integrity_note = (
            f"جمع اعلامی فایل ({int(declared_total_rial):,} ریال) با جمع محاسبه‌شده از "
            f"ردیف‌ها ({computed_total:,} ریال) برابر نیست — سند مشکوک است."
        )
    if parse.rejected:
        rejected_count = len(parse.rejected)
        prefix = f"{rejected_count} ردیف غیرقابل‌تفسیر رد شد."
        integrity_note = f"{integrity_note} {prefix}".strip()

    statement = SettlementStatement.objects.create(
        gateway_name=gateway_name,
        source_kind=source_kind,
        statement_sha256=fingerprint,
        original_filename=original_filename[:200],
        period_start=period_start,
        period_end=period_end,
        row_count=len(parse.rows) + len(parse.rejected),
        declared_total_rial=int(declared_total_rial)
        if declared_total_rial is not None
        else computed_total,
        computed_total_rial=computed_total,
        integrity_ok=integrity_ok,
        integrity_note=integrity_note[:300],
        status=SettlementStatementStatus.INGESTED,
        ingested_by=actor,
        raw_document={
            **dict(statement_metadata or {}),
            "rejected_rows": [
                {"row_number": r.row_number, "error": r.error, "payload": r.raw_payload}
                for r in parse.rejected
            ],
        },
    )

    SettlementRow.objects.bulk_create(
        [
            SettlementRow(
                statement=statement,
                row_number=row.row_number,
                authority=row.authority,
                ref_id=row.ref_id,
                amount_rial=row.amount_rial,
                occurred_at=row.occurred_at,
                card_pan_masked=row.card_pan_masked,
                description=row.description,
                raw_payload=row.raw_payload,
            )
            for row in parse.rows
        ],
        batch_size=500,
    )

    return statement, parse, True


# ══════════════════════════════════════════════════════════════════════════════
# ۲) تطبیق سه‌طرفه
# ══════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class ReconciliationStats:
    """آمار قابل‌گزارش یک اجرای تطبیق."""

    matched: int = 0
    amount_mismatch: int = 0
    missing_internal: int = 0
    missing_gateway: int = 0
    internal_not_verified: int = 0
    duplicate_in_file: int = 0
    financial_impact_rial: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "matched": self.matched,
            "amount_mismatch": self.amount_mismatch,
            "missing_internal": self.missing_internal,
            "missing_gateway": self.missing_gateway,
            "internal_not_verified": self.internal_not_verified,
            "duplicate_in_file": self.duplicate_in_file,
            "financial_impact_rial": self.financial_impact_rial,
        }

    @property
    def total_discrepancies(self) -> int:
        return (
            self.amount_mismatch
            + self.missing_internal
            + self.missing_gateway
            + self.internal_not_verified
            + self.duplicate_in_file
        )


@transaction.atomic
def reconcile_settlement_statement(
    *,
    statement_id: Any,
    actor: Any = None,
    dry_run: bool = True,
) -> tuple[SettlementReconciliation | ReconciliationStats, ReconciliationStats]:
    """تطبیق همهٔ ردیف‌های یک سند با پرداخت‌های داخلی.

    خروجی: ``(persisted_run_or_stats, stats)``.
        در ``dry_run`` هیچ رکوردی نوشته نمی‌شود و فقط آمار برمی‌گردد؛ در حالت
        واقعی، هم ردیف‌ها به‌روزرسانی می‌شوند و هم یک ``SettlementReconciliation``
        به‌عنوان عکس فوری قابل ممیزی ساخته می‌شود.

    چرا ``dry_run`` پیش‌فرض ``True`` است؟
        این عملیات روی پرونده‌های مالی اجرا می‌شود و ممکن است وضعیت حقیقت
        صدها پرداخت را تغییر بدهد. پیش‌فرض باید بی‌خطر باشد. اپراتور باید
        صریحاً بگوید «اجرا کن» — نه این‌که صریحاً بگوید «فقط نشانم بده».
    """
    statement = SettlementStatement.objects.filter(pk=statement_id).first()
    if statement is None:
        raise NotFoundError("سند صورت‌حساب تسویه یافت نشد.")

    rows = list(SettlementRow.objects.filter(statement=statement).order_by("row_number"))
    stats = ReconciliationStats()

    # ── شمارش تکرار Authority در خود فایل ──────────────────────────────────────
    authority_counts: dict[str, int] = {}
    for row in rows:
        if row.authority:
            authority_counts[row.authority] = authority_counts.get(row.authority, 0) + 1
    duplicated_authorities = {a for a, c in authority_counts.items() if c > 1}

    # ── بارگذاری پرداخت‌های داخلی مرتبط (یک کوئری، نه N کوئری) ────────────────
    authorities = [row.authority for row in rows if row.authority]
    payments_by_authority: dict[str, Payment] = {
        p.authority: p for p in Payment.objects.filter(authority__in=authorities)
    }

    now = timezone_now()
    rows_to_update: list[SettlementRow] = []
    seen_in_statement: set[str] = set()

    for row in rows:
        if not row.authority:
            row.match_status = SettlementRowMatchStatus.MISSING_INTERNAL
            row.match_note = "ردیف بدون شناسهٔ Authority در فایل — قابل تطبیق نیست."
            stats.missing_internal += 1
            rows_to_update.append(row)
            continue

        if row.authority in duplicated_authorities and row.authority not in seen_in_statement:
            # اولین تکرار: تطبیق معمول؛ تکرارهای بعدی علامت می‌خورند.
            pass
        elif row.authority in duplicated_authorities:
            row.match_status = SettlementRowMatchStatus.DUPLICATE_IN_FILE
            row.match_note = (
                f"Authority «{row.authority}» بیش از یک بار در همین فایل آمده است؛ "
                "فایل معیوب است و نباید مبنای اقدام خودکار باشد."
            )
            stats.duplicate_in_file += 1
            rows_to_update.append(row)
            continue

        seen_in_statement.add(row.authority)
        payment = payments_by_authority.get(row.authority)

        if payment is None:
            row.match_status = SettlementRowMatchStatus.MISSING_INTERNAL
            row.match_note = (
                f"ردیف {row.amount_rial:,} ریالی در صورتحساب هست اما هیچ پرداختی با این "
                "Authority در سامانه وجود ندارد — پول بی‌مالک."
            )
            row.payment = None
            stats.missing_internal += 1
            stats.financial_impact_rial += row.amount_rial
        elif int(payment.amount_rial) != int(row.amount_rial):
            row.match_status = SettlementRowMatchStatus.AMOUNT_MISMATCH
            diff = row.amount_rial - int(payment.amount_rial)
            row.match_note = (
                f"مبلغ صورتحساب {row.amount_rial:,} ریال و مبلغ داخلی "
                f"{int(payment.amount_rial):,} ریال است (اختلاف {diff:+,} ریال)."
            )
            row.payment = payment
            stats.amount_mismatch += 1
            stats.financial_impact_rial += diff
        elif payment.status not in {PaymentStatus.VERIFIED, PaymentStatus.REFUNDED}:
            row.match_status = SettlementRowMatchStatus.INTERNAL_NOT_VERIFIED
            row.match_note = (
                f"درگاه پول را گرفته ولی پرداخت داخلی در وضعیت «{payment.get_status_display()}» "
                "مانده است — قابل خوددرمانی با موتور داوری."
            )
            row.payment = payment
            stats.internal_not_verified += 1
            stats.financial_impact_rial += row.amount_rial
        else:
            row.match_status = SettlementRowMatchStatus.MATCHED
            row.match_note = "منطبق با پرداخت تأییدشدهٔ داخلی."
            row.payment = payment
            stats.matched += 1
            # تنها جایی که «حقیقت مستقل» را روی پرداخت مهر می‌زنیم.
            payment.truth_state = PaymentTruthState.STATEMENT_CONFIRMED
            payment.truth_confirmed_at = now
            payment.save(update_fields=["truth_state", "truth_confirmed_at", "updated_at"])

        rows_to_update.append(row)

    # ── جهت معکوس: پرداخت‌های تأییدشده‌ای که در فایل نیستند ────────────────────
    verified_in_period = Payment.objects.filter(
        gateway_name=statement.gateway_name,
        status=PaymentStatus.VERIFIED,
        verified_at__gte=statement.period_start,
        verified_at__lte=statement.period_end,
    ).exclude(authority__in=seen_in_statement)

    for payment in verified_in_period:
        # این پرداخت‌ها ردیف فایل ندارند؛ برای دیده‌شدن باید ردیف مصنوعی بسازیم
        # یا فقط روی خود پرداخت علامت بزنیم. تصمیم: علامت روی پرداخت + شمارش،
        # بدون ساختن ردیف جعلی در صورتحساب (چون فایل نگفته و ما نباید به آن
        # نسبت دروغ بدهیم).
        payment.truth_state = PaymentTruthState.STATEMENT_MISSING
        payment.save(update_fields=["truth_state", "updated_at"])
        stats.missing_gateway += 1
        stats.financial_impact_rial -= int(payment.amount_rial)

    if dry_run:
        # در اجرای آزمایشی هیچ چیز نوشته نمی‌شود؛ حتی برچسب حقیقت پرداخت‌ها.
        # برای همین، تغییرات روی اشیای درون‌حافظه‌ای را برمی‌گردانیم.
        transaction.set_rollback(True)
        return stats, stats

    SettlementRow.objects.bulk_update(
        rows_to_update,
        [
            "match_status",
            "match_note",
            "payment",
            "updated_at",
        ],
        batch_size=500,
    )

    statement.status = SettlementStatementStatus.MATCHED
    statement.save(update_fields=["status", "updated_at"])

    run = SettlementReconciliation.objects.create(
        statement=statement,
        matched_count=stats.matched,
        amount_mismatch_count=stats.amount_mismatch,
        missing_internal_count=stats.missing_internal,
        missing_gateway_count=stats.missing_gateway,
        internal_not_verified_count=stats.internal_not_verified,
        duplicate_in_file_count=stats.duplicate_in_file,
        integrity_violations=(
            0 if statement.integrity_ok else len(statement.raw_document.get("rejected_rows", []))
        ),
        financial_impact_rial=stats.financial_impact_rial,
        is_clean=stats.total_discrepancies == 0 and statement.integrity_ok,
        dry_run=False,
        reconciled_by=actor,
        notes={
            "policy": _truth_policy(),
            "statement_integrity_ok": statement.integrity_ok,
            "row_count": statement.row_count,
        },
    )
    return run, stats


def timezone_now() -> datetime:
    """زمان فعلی aware — استخراج‌شده تا تست بتواند آن را patch کند."""
    from django.utils import timezone as dj_timezone

    return dj_timezone.now()


# ══════════════════════════════════════════════════════════════════════════════
# ۳) اقدام (Remediation) — تنها جایی که این ماژول «کاری می‌کند»
#
# قاعدهٔ آهنین: خوددرمانی فقط در **یک** حالت مجاز است — ``INTERNAL_NOT_VERIFIED``
# یعنی صورتحساب می‌گوید درگاه پول را گرفته ولی پرداخت داخلی تأیید نشده. این
# حالت بی‌ابهام است و مسیر رفعش از قبل وجود دارد: همان ``reconcile_one_abandoned_payment``
# که در فاز ۱ ساختیم. ما اینجا هیچ منطق تأیید پرداخت تازه‌ای نمی‌سازیم؛ فقط
# موتور موجود را صدا می‌زنیم. اگر این وسوسه پیش بیاید که «هیچ، خودمان مستقیم
# تخصیص بزنیم که سریع‌تر است» — همان لحظه است که دو مسیر موازی برای یک
# تصمیم مالی ساخته‌ایم و از آن به بعد هیچ‌کس نمی‌داند کدام حقیقت است.
# ══════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class RemediationOutcome:
    """نتیجهٔ اجرای مرحلهٔ اقدام روی یک سند."""

    statement_id: str
    auto_healed: int = 0
    queued_review: int = 0
    blocked: int = 0
    skipped: int = 0
    already_resolved: int = 0
    heal_details: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "statement_id": self.statement_id,
            "auto_healed": self.auto_healed,
            "queued_review": self.queued_review,
            "blocked": self.blocked,
            "skipped": self.skipped,
            "already_resolved": self.already_resolved,
            "heal_details": self.heal_details,
        }


def remediate_settlement_statement(
    *,
    statement_id: Any,
    actor: Any = None,
    dry_run: bool = True,
) -> RemediationOutcome:
    """اجرای اقدام‌های مجاز خودکار روی ردیف‌های مغایرت‌دار یک سند.

    چرا این تابع از ``reconcile_*`` جدا است؟
        تطبیق فقط می‌خواند و می‌سنجد. اقدام، پول را در دفتر به حرکت درمی‌آورد.
        جدا کردنشان یعنی می‌توانیم بارها تطبیق بزنیم بدون آن‌که نگران اثر مالی
        باشیم. همچنین اجازه می‌دهد خوددرمانی برای یک بازهٔ مشخص و با تأیید
        انسانی جداگانه انجام شود — که همان چیزی است که «چهارچشمی» می‌خواهد.
    """
    # موتور داوری از طریق رجیستری پورت صدا زده می‌شود، نه import مستقیم.
    # چرا؟ ``services`` خودش به ``identity`` → ``audit`` → ``core.middleware``
    # زنجیره دارد و ``core.metrics`` هم به این ماژول نگاه می‌کند. import مستقیم
    # یک چرخهٔ واقعی می‌سازد (اثبات‌شده با گیت DAG)؛ پورت آن را به لبهٔ
    # زمان‌اجرا تبدیل می‌کند و ضمناً تست می‌تواند موتور را جایگزین کند.
    if _RECOVERY_ENGINE is None:
        raise NotImplementedError(
            "موتور داوری ثبت نشده است؛ apps.contributions.apps باید register_recovery_engine را صدا بزند."
        )
    reconcile_one_abandoned_payment = _RECOVERY_ENGINE

    statement = SettlementStatement.objects.filter(pk=statement_id).first()
    if statement is None:
        raise NotFoundError("سند صورت‌حساب تسویه یافت نشد.")

    del actor  # اقدام خودکار توسط سامانه انجام می‌شود؛ کاربر در ممیزی سند ثبت است
    outcome = RemediationOutcome(statement_id=str(statement.pk))
    policy = _truth_policy()

    rows = SettlementRow.objects.filter(
        statement=statement, match_status=SettlementRowMatchStatus.INTERNAL_NOT_VERIFIED
    ).select_related("payment")

    file_is_trustworthy = statement.integrity_ok

    for row in rows:
        payment = row.payment
        if payment is None:  # pragma: no cover - دفاعی؛ ردیف این حالت را باید داشته باشد
            row.remediation = SettlementRemediation.QUEUED_REVIEW
            row.remediation_note = "ردیف بدون ارتباط با پرداخت داخلی — بررسی انسانی لازم است."
            outcome.queued_review += 1
            if not dry_run:
                row.save(update_fields=["remediation", "remediation_note", "updated_at"])
            continue

        # ── دروازهٔ ۱: صحت سند ────────────────────────────────────────────────
        if not file_is_trustworthy:
            row.remediation = SettlementRemediation.BLOCKED
            row.remediation_note = (
                "سند از نظر صحت داخلی معیوب است (جمع اعلامی ≠ جمع محاسبه‌شده)؛ "
                "اقدام خودکار روی سند مشکوک مجاز نیست."
            )
            outcome.blocked += 1
            if not dry_run:
                row.save(update_fields=["remediation", "remediation_note", "updated_at"])
            continue

        # ── دروازهٔ ۲: کلید اصلی سیاست ─────────────────────────────────────────
        if not policy["auto_heal_enabled"]:
            row.remediation = SettlementRemediation.QUEUED_REVIEW
            row.remediation_note = (
                "خوددرمانی خودکار توسط سیاست «truth.auto_heal_enabled» خاموش است."
            )
            outcome.queued_review += 1
            if not dry_run:
                row.save(update_fields=["remediation", "remediation_note", "updated_at"])
            continue

        # ── دروازهٔ ۳: سقف ریالی ──────────────────────────────────────────────
        cap = policy["auto_heal_max_rial"]
        if cap > 0 and int(payment.amount_rial) > cap:
            row.remediation = SettlementRemediation.QUEUED_REVIEW
            row.remediation_note = (
                f"مبلغ {int(payment.amount_rial):,} ریال از سقف خوددرمانی خودکار "
                f"({cap:,} ریال) بیشتر است؛ نیازمند تأیید انسانی."
            )
            outcome.queued_review += 1
            if not dry_run:
                row.save(update_fields=["remediation", "remediation_note", "updated_at"])
            continue

        # ── دروازهٔ ۴: خوددرمانی با موتور موجود (بدون منطق موازی) ─────────────
        if dry_run:
            outcome.auto_healed += 1
            outcome.heal_details.append(
                {
                    "row": row.row_number,
                    "authority": row.authority,
                    "amount_rial": int(payment.amount_rial),
                    "would_call": "reconcile_one_abandoned_payment",
                }
            )
            continue

        try:
            verdict = reconcile_one_abandoned_payment(payment_id=payment.pk)
        except Exception as exc:
            row.remediation = SettlementRemediation.QUEUED_REVIEW
            row.remediation_note = f"خوددرمانی با خطا متوقف شد: {type(exc).__name__}"[:400]
            outcome.queued_review += 1
            row.save(update_fields=["remediation", "remediation_note", "updated_at"])
            continue

        if verdict in {LateCaptureOutcome.RECOVERED, LateCaptureOutcome.NOT_CAPTURED}:
            row.remediation = SettlementRemediation.AUTO_HEALED
            row.remediation_note = f"موتور داوری با نتیجهٔ «{verdict}» پرونده را بست."[:400]
            row.remediated_at = timezone_now()
            outcome.auto_healed += 1
            outcome.heal_details.append(
                {
                    "row": row.row_number,
                    "authority": row.authority,
                    "verdict": str(verdict),
                }
            )
        elif verdict == LateCaptureOutcome.REFUND_PENDING:
            row.remediation = SettlementRemediation.AUTO_HEALED
            row.remediation_note = (
                "موتور داوری وجه را تأیید کرد ولی ظرفیت نبود؛ تعهد بازپرداخت ساخته شد."
            )
            row.remediated_at = timezone_now()
            outcome.auto_healed += 1
            outcome.heal_details.append(
                {"row": row.row_number, "authority": row.authority, "verdict": "refund_pending"}
            )
        else:
            # MANUAL_REVIEW یا هر نتیجهٔ نامعلوم: انسان باید ببیند.
            row.remediation = SettlementRemediation.QUEUED_REVIEW
            row.remediation_note = (
                f"موتور داوری به نتیجهٔ قطعی نرسید («{verdict}»)؛ پرونده به بررسی انسانی رفت."
            )[:400]
            outcome.queued_review += 1

        row.save(update_fields=["remediation", "remediation_note", "remediated_at", "updated_at"])

    # ── ردیف‌های غیرقابل‌درمان خودکار: همه در صف بررسی ────────────────────────
    review_worthy = SettlementRow.objects.filter(statement=statement).exclude(
        match_status__in={
            SettlementRowMatchStatus.MATCHED,
            SettlementRowMatchStatus.INTERNAL_NOT_VERIFIED,
            SettlementRowMatchStatus.PENDING,
        }
    )
    if not dry_run:
        for row in review_worthy:
            if row.remediation == SettlementRemediation.NONE:
                row.remediation = SettlementRemediation.QUEUED_REVIEW
                row.remediation_note = row.match_note[:400] or "نیازمند بررسی انسانی."
                row.save(update_fields=["remediation", "remediation_note", "updated_at"])
                outcome.queued_review += 1
    else:
        outcome.queued_review += review_worthy.filter(
            remediation=SettlementRemediation.NONE
        ).count()

    if not dry_run and outcome.auto_healed and not review_worthy.exists():
        statement.status = SettlementStatementStatus.CLOSED
        statement.save(update_fields=["status", "updated_at"])

    return outcome


# ══════════════════════════════════════════════════════════════════════════════
# ۴) پنل «حقیقت وجه» — عددی که می‌شود به هیئت‌مدیره گفت
# ══════════════════════════════════════════════════════════════════════════════


def build_money_truth_panel() -> dict[str, Any]:
    """عکس لحظه‌ای از فاصلهٔ «چیزی که ما می‌گوییم» و «چیزی که بانک می‌گوید».

    این پنل عمداً ساده است: مدیر باید در پنج ثانیه بفهمد باید نگران باشد یا نه.
    همهٔ اعداد یا «صفر» هستند (خوب) یا «غیرصفر» (باید بررسی شود). هیچ عددی
    برای زیبایی نمایش داده نمی‌شود.
    """
    now = timezone_now()

    # «تأییدشدهٔ خودگواه» یعنی ما گفتیم موفق است ولی هیچ سند مستقلی آن را
    # تأیید نکرده — و مهم نیست چرا: UNVERIFIED (سندی ندیده)، SELF_REPORTED
    # (فقط verify خودگواه) یا STATEMENT_MISSING (سند دید ولی او را نداشت).
    # هر سه در نگاه مدیر یعنی «این عدد قابل ارائه به هیئت‌مدیره نیست».
    verified_but_unconfirmed = Payment.objects.filter(
        status=PaymentStatus.VERIFIED,
        truth_state__in=[
            PaymentTruthState.UNVERIFIED,
            PaymentTruthState.SELF_REPORTED,
            PaymentTruthState.STATEMENT_MISSING,
        ],
    ).count()
    statement_confirmed = Payment.objects.filter(
        truth_state=PaymentTruthState.STATEMENT_CONFIRMED
    ).count()
    statement_missing = Payment.objects.filter(
        truth_state=PaymentTruthState.STATEMENT_MISSING
    ).count()
    conflict = Payment.objects.filter(truth_state=PaymentTruthState.CONFLICT).count()

    last_statement = SettlementStatement.objects.order_by("-created_at").first()
    age_hours: float | None = None
    if last_statement is not None:
        age_hours = round((now - last_statement.created_at).total_seconds() / 3600.0, 2)

    first_run_statuses = [
        SettlementRowMatchStatus.AMOUNT_MISMATCH,
        SettlementRowMatchStatus.MISSING_INTERNAL,
        SettlementRowMatchStatus.MISSING_GATEWAY,
        SettlementRowMatchStatus.INTERNAL_NOT_VERIFIED,
        SettlementRowMatchStatus.DUPLICATE_IN_FILE,
    ]
    unresolved_rows = SettlementRow.objects.filter(match_status__in=first_run_statuses).exclude(
        remediation__in=[SettlementRemediation.AUTO_HEALED, SettlementRemediation.MANUAL_RESOLVED]
    )

    unresolved_impact = 0
    for row in unresolved_rows.select_related("payment").only(
        "amount_rial", "match_status", "payment"
    ):
        if row.match_status == SettlementRowMatchStatus.AMOUNT_MISMATCH and row.payment is not None:
            unresolved_impact += int(row.amount_rial) - int(row.payment.amount_rial)
        elif row.match_status in {
            SettlementRowMatchStatus.MISSING_INTERNAL,
            SettlementRowMatchStatus.INTERNAL_NOT_VERIFIED,
        }:
            unresolved_impact += int(row.amount_rial)

    return {
        "verified_but_unconfirmed": verified_but_unconfirmed,
        "statement_confirmed": statement_confirmed,
        "statement_missing": statement_missing,
        "conflict": conflict,
        "last_statement_at": last_statement.created_at if last_statement else None,
        "statement_age_hours": age_hours,
        "unresolved_findings": unresolved_rows.count(),
        "unresolved_impact_rial": unresolved_impact,
        "statements_total": SettlementStatement.objects.count(),
        "rows_pending_verdict": SettlementRow.objects.filter(
            match_status=SettlementRowMatchStatus.PENDING
        ).count(),
    }


def money_truth_alerts() -> list[dict[str, Any]]:
    """هشدارهای ماشین‌خوان لایهٔ حقیقت — برای ادغام در پنل سلامت مالی.

    هر هشدار سه فیلد دارد: ``level`` (critical/warning/info)، ``code`` (ثابت و
    ماشین‌خوان) و ``message`` (فارسی و انسانی). سامانهٔ هشدار می‌تواند روی
    ``code`` قاعده بسازد بدون آنکه به متن فارسی وابسته شود.
    """
    panel = build_money_truth_panel()
    policy = _truth_policy()
    alerts: list[dict[str, Any]] = []

    if panel["conflict"] > 0:
        alerts.append(
            {
                "level": "critical",
                "code": "money_truth_conflict",
                "message": (
                    f"{panel['conflict']} پرداخت بین دفتر داخلی و صورتحساب درگاه در تناقض قطعی است."
                ),
            }
        )
    if panel["statement_missing"] > 0:
        alerts.append(
            {
                "level": "warning",
                "code": "statement_missing_payments",
                "message": (
                    f"{panel['statement_missing']} پرداخت تأییدشده در صورتحساب اخیر درگاه نبود "
                    "— ممکن است فایل ناقص باشد یا پول واقعاً تسویه نشده باشد."
                ),
            }
        )
    max_age = policy["max_statement_age_hours"]
    age = panel["statement_age_hours"]
    if age is None:
        # سامانه‌ای که هنوز هیچ تراکنشی ندارد، طبیعتاً صورت‌حسابی هم ندارد؛
        # هشدار دادن در روز اول = هشدار کاذب = بی‌اعتبار کردن کل پنل.
        # ولی به‌محض اینکه پولی جابه‌جا شده و هنوز هیچ سندی نیامده، چشم
        # مستقل واقعاً کور است و باید «بحرانی» اعلام شود.
        if panel["verified_but_unconfirmed"] > 0:
            alerts.append(
                {
                    "level": "critical",
                    "code": "no_settlement_statement_with_money",
                    "message": (
                        f"{panel['verified_but_unconfirmed']} پرداخت تأییدشده داریم ولی "
                        "هیچ صورت‌حساب تسویه‌ای هرگز وارد نشده — هیچ ریالی به‌طور مستقل تأیید نشده."
                    ),
                }
            )
    elif age > max_age:
        alerts.append(
            {
                "level": "critical",
                "code": "stale_settlement_statement",
                "message": (
                    f"آخرین صورت‌حساب {age:.1f} ساعت پیش وارد شده (آستانه: {max_age} ساعت). "
                    "چشم مستقل کور شده است."
                ),
            }
        )
    if panel["unresolved_impact_rial"] >= policy["unresolved_impact_alert_rial"]:
        alerts.append(
            {
                "level": "warning",
                "code": "unresolved_financial_impact",
                "message": (
                    f"اثر ریالی مغایرت‌های حل‌نشده {panel['unresolved_impact_rial']:,} ریال است "
                    f"(آستانه: {policy['unresolved_impact_alert_rial']:,} ریال)."
                ),
            }
        )
    if panel["rows_pending_verdict"] > 0:
        alerts.append(
            {
                "level": "info",
                "code": "rows_pending_reconciliation",
                "message": (f"{panel['rows_pending_verdict']} ردیف صورت‌حساب هنوز تطبیق نشده است."),
            }
        )
    return alerts
