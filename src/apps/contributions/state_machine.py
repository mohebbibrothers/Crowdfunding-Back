"""ماشین حالت صریح چرخهٔ حیات مشارکت و پرداخت (Single Source of Truth).

چرا این ماژول وجود دارد؟
    چرخهٔ پول در یک سامانهٔ خیریه‌ای سه‌گانه است: «رزرو → پرداخت → تخصیص سهم».
    وقتی رزرو منقضی می‌شود ولی پول پیش‌تر گرفته شده باشد، سیستم وارد ناحیه‌ای
    می‌شود که هیچ مسیر خوش‌بینانه‌ای ندارد. اگر این گذارها در سراسر کدبیس
    پراکنده باشند (چند فایل، چند شرط ``if``)، دیر یا زود یک مسیر جا می‌افتد و
    «پول گم‌شده» تولید می‌شود.

    این ماژول همان گذارها را *داده* می‌کند، نه کد؛ و یک آزمون معماری
    (``test_state_machine_covers_every_runtime_transition``) تضمین می‌کند
    هر وضعیتی که در کد واقعاً نوشته می‌شود در این جدول اعلان شده باشد.
"""

from __future__ import annotations

from typing import Final

from apps.contributions.choices import ContributionStatus, PaymentStatus

# ── گراف مشارکت ──────────────────────────────────────────────────────────────
# خواندن: «از وضعیت کلید، به کدام وضعیت‌ها می‌توان رفت؟»
CONTRIBUTION_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    ContributionStatus.RESERVED: frozenset(
        {
            ContributionStatus.PAID,  # مسیر عادی: تأیید درگاه
            ContributionStatus.FAILED,  # رد صریح درگاه یا انصراف کاربر
            ContributionStatus.EXPIRED,  # رزرو ۱۵ دقیقه‌ای تمام شد
        }
    ),
    ContributionStatus.EXPIRED: frozenset(
        {
            # مسیر نجات: پول گرفته شده و سهم همان لحظه تخصیص یافت
            ContributionStatus.CAPTURED_LATE,
            # مسیر نجات: پول گرفته شده ولی ظرفیت نیست ⇒ بازپرداخت اجباری
            ContributionStatus.AWAITING_REFUND,
        }
    ),
    ContributionStatus.FAILED: frozenset({ContributionStatus.PAID}),
    ContributionStatus.CAPTURED_LATE: frozenset({ContributionStatus.REFUNDED}),
    ContributionStatus.AWAITING_REFUND: frozenset(
        {
            ContributionStatus.REFUNDED,
            # اگر مدیر مالی به‌جای بازپرداخت، ظرفیت آزاد کرد و سهم را داد
            ContributionStatus.CAPTURED_LATE,
        }
    ),
    ContributionStatus.PAID: frozenset({ContributionStatus.REFUNDED}),
    ContributionStatus.REFUNDED: frozenset(),  # پایانه
}

# ── گراف پرداخت ──────────────────────────────────────────────────────────────
PAYMENT_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    PaymentStatus.INITIATED: frozenset(
        {
            PaymentStatus.VERIFIED,
            PaymentStatus.FAILED,
            PaymentStatus.ABANDONED,
        }
    ),
    PaymentStatus.ABANDONED: frozenset(
        {
            # داوری خودکار با درگاه
            PaymentStatus.VERIFIED,
            PaymentStatus.FAILED,
        }
    ),
    PaymentStatus.FAILED: frozenset({PaymentStatus.VERIFIED}),
    PaymentStatus.VERIFIED: frozenset({PaymentStatus.REFUNDED}),
    PaymentStatus.REFUNDED: frozenset(),  # پایانه
}

# وضعیت‌هایی که «پول واقعاً نزد درگاه است» و هرگز نباید بازپرداخت‌شان گم شود.
MONEY_AT_GATEWAY_STATUSES: Final[frozenset[str]] = frozenset(
    {
        ContributionStatus.PAID,
        ContributionStatus.CAPTURED_LATE,
        ContributionStatus.AWAITING_REFUND,
    }
)

# وضعیت‌های پایانه‌ای که نباید هیچ گذار خروجی داشته باشند.
TERMINAL_CONTRIBUTION_STATUSES: Final[frozenset[str]] = frozenset({ContributionStatus.REFUNDED})


class IllegalTransitionError(ValueError):
    """گذار درخواستی در گراف حالت مجاز نیست (خطای برنامه‌نویس، نه کاربر)."""


def can_contribution_transition(current: str, target: str) -> bool:
    """آیا رفتن از ``current`` به ``target`` در گراف مشارکت مجاز است؟"""
    return target in CONTRIBUTION_TRANSITIONS.get(current, frozenset())


def can_payment_transition(current: str, target: str) -> bool:
    """آیا رفتن از ``current`` به ``target`` در گراف پرداخت مجاز است؟"""
    return target in PAYMENT_TRANSITIONS.get(current, frozenset())


def assert_contribution_transition(current: str, target: str) -> None:
    """اعتبارسنجی سخت گذار مشارکت یا پرتاب ``IllegalTransitionError``."""
    if current == target:
        return
    if not can_contribution_transition(current, target):
        msg = (
            f"گذار غیرمجاز مشارکت: «{current}» → «{target}». "
            f"گذارهای مجاز: {sorted(CONTRIBUTION_TRANSITIONS.get(current, ()))}"
        )
        raise IllegalTransitionError(msg)


def assert_payment_transition(current: str, target: str) -> None:
    """اعتبارسنجی سخت گذار پرداخت یا پرتاب ``IllegalTransitionError``."""
    if current == target:
        return
    if not can_payment_transition(current, target):
        msg = (
            f"گذار غیرمجاز پرداخت: «{current}» → «{target}». "
            f"گذارهای مجاز: {sorted(PAYMENT_TRANSITIONS.get(current, ()))}"
        )
        raise IllegalTransitionError(msg)


def reaches_money_capture(status: str) -> bool:
    """آیا این وضعیت مشارکت یعنی «پول نزد درگاه است و باید تعیین تکلیف شود»؟"""
    return status in MONEY_AT_GATEWAY_STATUSES
