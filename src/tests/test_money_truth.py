"""آزمون‌های لایهٔ حقیقت وجه — صورت‌حساب مستقل تسویهٔ درگاه.

فلسفهٔ این فایل: هر آزمون باید بتواند **در دنیای واقعی خراب شود**. یعنی اگر
منطقش را قاطی کنی، این یک تست است که می‌گیرد، نه یک تست که همیشه سبز است.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.cache import cache
from django.utils import timezone
import pytest

from apps.contributions.choices import (
    ContributionStatus,
    PaymentStatus,
    PaymentTruthState,
    SettlementRemediation,
    SettlementRowMatchStatus,
    SettlementSourceKind,
    SettlementStatementStatus,
)
from apps.contributions.models import (
    Contribution,
    Payment,
    SettlementReconciliation,
    SettlementRow,
    SettlementStatement,
)
from apps.contributions.settlement import (
    compute_statement_fingerprint,
    ingest_settlement_statement,
    normalize_amount_rial,
    normalize_authority,
    normalize_datetime,
    parse_settlement_rows,
    reconcile_settlement_statement,
    remediate_settlement_statement,
)
from apps.core.errors import ValidationError as DomainValidationError
from tests.test_capture_recovery import _admin, _campaign, _donor

# ══════════════════════════════════════════════════════════════════════════════
# نرمال‌سازی — جایی که بیشتر باگ‌های واقعی متولد می‌شوند
# ══════════════════════════════════════════════════════════════════════════════


def test_persian_digits_and_separators_parse_to_int() -> None:
    """«۱٬۲۵۰٬۰۰۰» باید 1250000 شود — نه 0، نه خطا."""
    assert normalize_amount_rial("۱٬۲۵۰٬۰۰۰") == 1_250_000
    assert normalize_amount_rial("۱۲۵۰۰۰۰") == 1_250_000
    assert normalize_amount_rial("1,250,000") == 1_250_000
    assert normalize_amount_rial(" 1250000 ") == 1_250_000
    assert normalize_amount_rial("1250000.00") == 1_250_000  # اکسل به‌شکل اعشار ذخیره می‌کند


def test_fractional_amount_is_rejected_not_rounded() -> None:
    """ریال عدد صحیح است. گردکردن در مسیر پول = گم‌شدن وجه."""
    with pytest.raises(DomainValidationError) as exc_info:
        normalize_amount_rial("1250000.75")
    assert getattr(exc_info.value, "code", "") == "settlement_fractional_amount"

    with pytest.raises(DomainValidationError):
        normalize_amount_rial("۱۲۵۰۰۰۰٫۵")  # جداکنندهٔ اعشار فارسی


def test_negative_amount_is_rejected() -> None:
    """مبلغ منفی در صورت‌حساب تسویه یعنی فایل معیوب یا دستکاری‌شده."""
    with pytest.raises(DomainValidationError) as exc_info:
        normalize_amount_rial("-1250000")
    assert getattr(exc_info.value, "code", "") == "settlement_invalid_amount"


def test_empty_amount_is_zero_not_error() -> None:
    """ردیف بی‌مبلغ در فایل‌های واقعی رخداد عادی است (سطر توضیح، جمع، …)."""
    assert normalize_amount_rial("") == 0
    assert normalize_amount_rial(None) == 0
    assert normalize_amount_rial("-") == 0
    assert normalize_amount_rial("—") == 0


def test_bool_is_not_accepted_as_amount() -> None:
    """``True`` زیرنوع ``int`` است؛ اگر رد نشود، ردیف ۱ ریالی جعلی می‌سازد."""
    with pytest.raises(DomainValidationError):
        normalize_amount_rial(True)


def test_authority_normalization_kills_false_mismatches() -> None:
    """``A1b2`` و `` a1B2 `` یک تراکنش‌اند؛ بدون نرمال‌سازی، «پول بی‌مالک» دروغ گزارش می‌شود."""
    assert normalize_authority("  a1b2c3  ") == "A1B2C3"
    assert normalize_authority("A1B2C3\x00") == "A1B2C3"
    assert normalize_authority(None) == ""


def test_datetime_accepts_iso_and_slash_forms() -> None:
    """تاریخ اشتباه = یک روز کامل تراکنش بیرون از بازهٔ تطبیق."""
    assert normalize_datetime("2026-11-12T08:30:00Z") == datetime(2026, 11, 12, 8, 30, tzinfo=UTC)
    assert normalize_datetime("2026-11-12 08:30") == datetime(2026, 11, 12, 8, 30, tzinfo=UTC)
    assert normalize_datetime("2026/11/12") == datetime(2026, 11, 12, tzinfo=UTC)
    assert normalize_datetime("") is None
    assert normalize_datetime("نامعتبر") is None


# ══════════════════════════════════════════════════════════════════════════════
# پارس ردیف‌ها
# ══════════════════════════════════════════════════════════════════════════════


def test_one_bad_row_does_not_kill_the_whole_file() -> None:
    """فایل واقعی همیشه یک سطر جمع دارد. رد کل سند = دست بستهٔ اپراتور."""
    outcome = parse_settlement_rows(
        [
            {"authority": "A1", "amount": "۱٬۰۰۰٬۰۰۰"},
            {"amount": "۵۰۰٬۰۰۰"},  # بدون Authority
            {"authority": "A2", "amount": "۲۰۰۰۰۰۰"},
        ]
    )
    assert len(outcome.rows) == 2
    assert len(outcome.rejected) == 1
    assert "Authority" in outcome.rejected[0].error
    assert outcome.computed_total_rial == 3_000_000


def test_column_aliases_are_recognized() -> None:
    """صادرات‌های مختلف بانک، نام ستون یکسان ندارند — ولی همه باید بخوانند."""
    for header in ("authority", "Authority", "شناسه تراکنش", "کد تراکنش"):
        outcome = parse_settlement_rows([{header: "X9", "مبلغ": "100000"}])
        assert outcome.rows[0].authority == "X9", f"header «{header}» شناخته نشد"
        assert outcome.rows[0].amount_rial == 100_000


def test_fingerprint_is_stable_across_formatting() -> None:
    """«۱٬۰۰۰٬۰۰۰» و «1000000» باید همان اثر انگشت را بدهند (وگرنه ورود تکراری تشخیص داده نمی‌شود)."""
    start = datetime(2026, 11, 1, tzinfo=UTC)
    end = datetime(2026, 11, 30, tzinfo=UTC)
    fp1 = compute_statement_fingerprint(
        gateway_name="zarinpal",
        period_start=start,
        period_end=end,
        rows=[{"authority": "a1", "amount": "۱٬۰۰۰٬۰۰۰"}],
    )
    fp2 = compute_statement_fingerprint(
        gateway_name="zarinpal",
        period_start=start,
        period_end=end,
        rows=[{"Authority": "A1", "amount_rial": 1_000_000}],
    )
    assert fp1 == fp2


def test_fingerprint_differs_across_gateways() -> None:
    """ردیف یکسان از دو درگاه، دو سند متفاوت است."""
    start = datetime(2026, 11, 1, tzinfo=UTC)
    end = datetime(2026, 11, 30, tzinfo=UTC)
    rows = [{"authority": "A1", "amount": 1_000_000}]
    fp1 = compute_statement_fingerprint(
        gateway_name="zarinpal", period_start=start, period_end=end, rows=rows
    )
    fp2 = compute_statement_fingerprint(
        gateway_name="sandbox", period_start=start, period_end=end, rows=rows
    )
    assert fp1 != fp2


# ══════════════════════════════════════════════════════════════════════════════
# ورود سند
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_same_file_twice_returns_same_statement(seeded_policies: None) -> None:
    """آپلود دوبارهٔ همان فایل نباید دو «حقیقت» موازی بسازد."""
    del seeded_policies
    admin = _admin("40")
    rows = [{"authority": "A1", "amount": 1_000_000}, {"authority": "A2", "amount": 2_000_000}]

    # بازه بخشی از «هویت» سند است و از خود فایل می‌آید، نه از ساعت دیوار.
    # اگر بازه را با timezone.now() بسازیم، هر آپلود بازهٔ متفاوتی دارد و
    # idempotency به‌طور مصنوعی می‌شکند — دقیقاً همان چیزی که این تست می‌گیرد.
    period_start = datetime(2026, 11, 1, tzinfo=UTC)
    period_end = datetime(2026, 11, 30, 23, 59, 59, tzinfo=UTC)

    first, _, created_first = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=period_start,
        period_end=period_end,
        raw_rows=rows,
        actor=admin,
    )
    second, _, created_second = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=period_start,
        period_end=period_end,
        raw_rows=rows,
        actor=admin,
    )

    assert created_first is True
    assert created_second is False
    assert first.pk == second.pk
    assert SettlementStatement.objects.count() == 1
    assert SettlementRow.objects.count() == 2  # ردیف تکراری ساخته نشد


@pytest.mark.django_db
def test_declared_total_mismatch_marks_integrity_violation(seeded_policies: None) -> None:
    """فایل معیوب باید صریحاً مشکوک علامت بخورد — نه بی‌صدا پذیرفته شود."""
    del seeded_policies
    admin = _admin("41")
    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=timezone.now() - timedelta(days=1),
        period_end=timezone.now(),
        raw_rows=[{"authority": "A1", "amount": 1_000_000}],
        declared_total_rial=9_999_999,  # ادعای فایل با واقعیت نمی‌خواند
        actor=admin,
    )
    assert statement.integrity_ok is False
    assert statement.computed_total_rial == 1_000_000
    assert statement.declared_total_rial == 9_999_999
    assert "برابر نیست" in statement.integrity_note


@pytest.mark.django_db
def test_invalid_period_is_rejected(seeded_policies: None) -> None:
    """بازهٔ معکوس یعنی ورودی معیوب؛ باید رد شود نه اینکه سند بی‌معنا بسازد."""
    del seeded_policies
    admin = _admin("42")
    with pytest.raises(DomainValidationError) as exc_info:
        ingest_settlement_statement(
            gateway_name="sandbox",
            source_kind=SettlementSourceKind.CSV,
            period_start=timezone.now(),
            period_end=timezone.now() - timedelta(days=1),
            raw_rows=[],
            actor=admin,
        )
    assert getattr(exc_info.value, "code", "") == "settlement_invalid_period"


# ══════════════════════════════════════════════════════════════════════════════
# تطبیق — قلب ماجرا
# ══════════════════════════════════════════════════════════════════════════════


_PHONE_SEQ = {"n": 60}


def _next_phone_suffix() -> str:
    """شمارهٔ موبایل یکتا برای هر فراخوانی — چون ``phone`` یکتاست."""
    _PHONE_SEQ["n"] += 1
    return f"{_PHONE_SEQ['n']:02d}"


def _verified_payment(
    *, admin: Any, suffix: str, amount: int = 1_000_000, authority: str = ""
) -> Payment:
    """ساخت یک پرداخت تأییدشدهٔ داخلی برای تطبیق."""
    campaign = _campaign(admin, slug_suffix=f"truth{suffix}")
    donor = _donor(_next_phone_suffix())
    contribution = Contribution.objects.create(
        user=donor,
        benefactor=campaign.benefactor,
        target_kind="campaign_shares",
        campaign=campaign,
        shares_count=1,
        amount_rial=amount,
        status=ContributionStatus.PAID,
        hold_expires_at=timezone.now(),
    )
    return Payment.objects.create(
        contribution=contribution,
        gateway_name="sandbox",
        authority=authority or f"SBX-TRUTH{suffix.upper()}",
        amount_rial=amount,
        redirect_url="https://sandbox.invalid/pay",
        status=PaymentStatus.VERIFIED,
        verified_at=timezone.now(),
    )


@pytest.mark.django_db
def test_matched_row_stamps_independent_truth(seeded_policies: None) -> None:
    """ردیف منطبق باید ``truth_state`` را به «تأییدشدهٔ مستقل» ارتقا دهد."""
    del seeded_policies
    admin = _admin("43")
    payment = _verified_payment(admin=admin, suffix="m1")
    assert payment.truth_state == PaymentTruthState.UNVERIFIED  # پیش‌فرض

    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=timezone.now() - timedelta(hours=2),
        period_end=timezone.now() + timedelta(hours=1),
        raw_rows=[{"authority": payment.authority, "amount": int(payment.amount_rial)}],
        actor=admin,
    )
    run, stats = reconcile_settlement_statement(
        statement_id=statement.pk, actor=admin, dry_run=False
    )

    assert stats.matched == 1
    assert stats.total_discrepancies == 0
    payment.refresh_from_db()
    assert payment.truth_state == PaymentTruthState.STATEMENT_CONFIRMED
    assert payment.truth_confirmed_at is not None
    assert run.is_clean is True


@pytest.mark.django_db
def test_row_without_internal_payment_is_orphan_money(seeded_policies: None) -> None:
    """پول در حساب ما هست، مالکش را نمی‌دانیم — بحرانی‌ترین حالت."""
    del seeded_policies
    admin = _admin("44")
    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=timezone.now() - timedelta(days=1),
        period_end=timezone.now(),
        raw_rows=[{"authority": "SBX-GHOST-999", "amount": 7_500_000}],
        actor=admin,
    )
    run, stats = reconcile_settlement_statement(
        statement_id=statement.pk, actor=admin, dry_run=False
    )

    assert stats.missing_internal == 1
    assert stats.financial_impact_rial == 7_500_000  # پول پیدا شد که در دفتر نبود
    assert run.is_clean is False

    row = SettlementRow.objects.get(statement=statement)
    assert row.match_status == SettlementRowMatchStatus.MISSING_INTERNAL
    assert "پول بی‌مالک" in row.match_note
    assert row.remediation == SettlementRemediation.NONE  # خودکار حل نمی‌شود


@pytest.mark.django_db
def test_amount_mismatch_is_flagged_with_signed_difference(seeded_policies: None) -> None:
    """اختلاف ریالی باید دقیقاً با علامتش گزارش شود — نه فقط «مغایرت»."""
    del seeded_policies
    admin = _admin("45")
    payment = _verified_payment(admin=admin, suffix="m2", amount=1_000_000)
    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=timezone.now() - timedelta(hours=2),
        period_end=timezone.now() + timedelta(hours=1),
        raw_rows=[{"authority": payment.authority, "amount": 1_250_000}],  # ۲۵۰ هزار بیشتر
        actor=admin,
    )
    _, stats = reconcile_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)

    assert stats.amount_mismatch == 1
    assert stats.financial_impact_rial == 250_000
    row = SettlementRow.objects.get(statement=statement)
    assert "+250,000" in row.match_note


@pytest.mark.django_db
def test_verified_internal_missing_from_statement(seeded_policies: None) -> None:
    """دفتر ما بدهی ثبت کرده که در صورتحساب نیست — بی‌سروصدا و خطرناک."""
    del seeded_policies
    admin = _admin("46")
    payment = _verified_payment(admin=admin, suffix="m3", amount=3_000_000)

    # سندی که این پرداخت را ندارد
    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=payment.verified_at - timedelta(minutes=5),
        period_end=payment.verified_at + timedelta(minutes=5),
        raw_rows=[{"authority": "SBX-OTHER", "amount": 500_000}],
        actor=admin,
    )
    _, stats = reconcile_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)

    assert stats.missing_gateway == 1
    payment.refresh_from_db()
    assert payment.truth_state == PaymentTruthState.STATEMENT_MISSING


@pytest.mark.django_db
def test_duplicate_authority_in_file_is_flagged(seeded_policies: None) -> None:
    """Authority تکراری در یک فایل یعنی فایل معیوب — نباید مبنای اقدام باشد."""
    del seeded_policies
    admin = _admin("47")
    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=timezone.now() - timedelta(days=1),
        period_end=timezone.now(),
        raw_rows=[
            {"authority": "SBX-DUP-1", "amount": 1_000_000},
            {"authority": "SBX-DUP-1", "amount": 1_000_000},  # تکراری
        ],
        actor=admin,
    )
    _, stats = reconcile_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)

    assert stats.duplicate_in_file == 1
    dup = SettlementRow.objects.get(statement=statement, row_number=2)
    assert dup.match_status == SettlementRowMatchStatus.DUPLICATE_IN_FILE
    assert "فایل معیوب" in dup.match_note


@pytest.mark.django_db
def test_dry_run_writes_nothing(seeded_policies: None) -> None:
    """اجرای آزمایشی باید کاملاً بی‌اثر باشد — حتی برچسب حقیقت پرداخت."""
    del seeded_policies
    admin = _admin("48")
    payment = _verified_payment(admin=admin, suffix="m4")
    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=timezone.now() - timedelta(hours=2),
        period_end=timezone.now() + timedelta(hours=1),
        raw_rows=[{"authority": payment.authority, "amount": int(payment.amount_rial)}],
        actor=admin,
    )

    _result, stats = reconcile_settlement_statement(
        statement_id=statement.pk, actor=admin, dry_run=True
    )

    assert stats.matched == 1
    assert SettlementReconciliation.objects.count() == 0
    payment.refresh_from_db()
    assert payment.truth_state == PaymentTruthState.UNVERIFIED  # دست‌نخورده
    row = SettlementRow.objects.get(statement=statement)
    assert row.match_status == SettlementRowMatchStatus.PENDING  # دست‌نخورده


# ══════════════════════════════════════════════════════════════════════════════
# خوددرمانی — تنها جایی که این لایه «کاری می‌کند»
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_internal_not_verified_is_auto_healed_by_existing_engine(seeded_policies: None) -> None:
    """درگاه پول گرفت و ما نگرفتیم ⇒ همان موتور داوری فاز ۱ باید حلش کند."""
    del seeded_policies
    admin = _admin("49")
    campaign = _campaign(admin, slug_suffix="heal1")
    donor = _donor("49")
    contribution = Contribution.objects.create(
        user=donor,
        benefactor=campaign.benefactor,
        target_kind="campaign_shares",
        campaign=campaign,
        shares_count=1,
        amount_rial=1_000_000,
        status=ContributionStatus.PAID,
        hold_expires_at=timezone.now(),
    )
    payment = Payment.objects.create(
        contribution=contribution,
        gateway_name="sandbox",
        authority="SBX-HEAL-0001",
        amount_rial=1_000_000,
        redirect_url="https://sandbox.invalid/pay",
        status=PaymentStatus.ABANDONED,  # پول گرفته شده ولی ما نفهمیدیم
    )

    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=timezone.now() - timedelta(days=1),
        period_end=timezone.now(),
        raw_rows=[{"authority": payment.authority, "amount": 1_000_000}],
        actor=admin,
    )
    reconcile_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)

    row = SettlementRow.objects.get(statement=statement)
    assert row.match_status == SettlementRowMatchStatus.INTERNAL_NOT_VERIFIED

    outcome = remediate_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)

    assert outcome.auto_healed == 1
    row.refresh_from_db()
    assert row.remediation == SettlementRemediation.AUTO_HEALED


@pytest.mark.django_db
def test_heal_above_cap_goes_to_human(seeded_policies: None) -> None:
    """بالای سقف سیاست، هیچ اقدام خودکاری مجاز نیست."""
    del seeded_policies
    from apps.core.models import PolicyRule

    PolicyRule.objects.update_or_create(
        key="truth.auto_heal_max_rial",
        defaults={"value_type": "int", "raw_value": 500_000, "description": "سقف آزمون"},
    )
    cache.clear()

    admin = _admin("50")
    campaign = _campaign(admin, slug_suffix="healcap")
    donor = _donor("50")
    contribution = Contribution.objects.create(
        user=donor,
        benefactor=campaign.benefactor,
        target_kind="campaign_shares",
        campaign=campaign,
        shares_count=1,
        amount_rial=5_000_000,  # بالای سقف
        status=ContributionStatus.PAID,
        hold_expires_at=timezone.now(),
    )
    payment = Payment.objects.create(
        contribution=contribution,
        gateway_name="sandbox",
        authority="SBX-HEALCAP01",
        amount_rial=5_000_000,
        redirect_url="https://sandbox.invalid/pay",
        status=PaymentStatus.ABANDONED,
    )
    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=timezone.now() - timedelta(days=1),
        period_end=timezone.now(),
        raw_rows=[{"authority": payment.authority, "amount": 5_000_000}],
        actor=admin,
    )
    reconcile_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)

    outcome = remediate_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)

    assert outcome.auto_healed == 0
    assert outcome.queued_review >= 1
    row = SettlementRow.objects.get(statement=statement)
    assert row.remediation == SettlementRemediation.QUEUED_REVIEW
    assert "سقف" in row.remediation_note


@pytest.mark.django_db
def test_auto_heal_disabled_policy_blocks_everything(seeded_policies: None) -> None:
    """کلید خاموش = هیچ اقدام خودکاری، حتی برای مبلغ کوچک."""
    del seeded_policies
    from apps.core.models import PolicyRule

    PolicyRule.objects.update_or_create(
        key="truth.auto_heal_enabled",
        defaults={"value_type": "bool", "raw_value": False, "description": "خاموش در آزمون"},
    )
    cache.clear()

    admin = _admin("51")
    campaign = _campaign(admin, slug_suffix="healoff")
    donor = _donor("51")
    contribution = Contribution.objects.create(
        user=donor,
        benefactor=campaign.benefactor,
        target_kind="campaign_shares",
        campaign=campaign,
        shares_count=1,
        amount_rial=100_000,
        status=ContributionStatus.PAID,
        hold_expires_at=timezone.now(),
    )
    payment = Payment.objects.create(
        contribution=contribution,
        gateway_name="sandbox",
        authority="SBX-HEALOFF01",
        amount_rial=100_000,
        redirect_url="https://sandbox.invalid/pay",
        status=PaymentStatus.ABANDONED,
    )
    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=timezone.now() - timedelta(days=1),
        period_end=timezone.now(),
        raw_rows=[{"authority": payment.authority, "amount": 100_000}],
        actor=admin,
    )
    reconcile_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)

    outcome = remediate_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)

    assert outcome.auto_healed == 0
    row = SettlementRow.objects.get(statement=statement)
    assert row.remediation == SettlementRemediation.QUEUED_REVIEW
    assert "خاموش" in row.remediation_note


@pytest.mark.django_db
def test_integrity_violation_blocks_auto_heal(seeded_policies: None) -> None:
    """سند معیوب هرگز نباید مبنای خروج پول یا تأیید خودکار باشد."""
    del seeded_policies
    admin = _admin("52")
    campaign = _campaign(admin, slug_suffix="healint")
    donor = _donor("52")
    contribution = Contribution.objects.create(
        user=donor,
        benefactor=campaign.benefactor,
        target_kind="campaign_shares",
        campaign=campaign,
        shares_count=1,
        amount_rial=500_000,
        status=ContributionStatus.PAID,
        hold_expires_at=timezone.now(),
    )
    payment = Payment.objects.create(
        contribution=contribution,
        gateway_name="sandbox",
        authority="SBX-HEALINT01",
        amount_rial=500_000,
        redirect_url="https://sandbox.invalid/pay",
        status=PaymentStatus.ABANDONED,
    )
    # جمع اعلامی دروغ ⇒ سند معیوب
    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=timezone.now() - timedelta(days=1),
        period_end=timezone.now(),
        raw_rows=[{"authority": payment.authority, "amount": 500_000}],
        declared_total_rial=999_999_999,
        actor=admin,
    )
    reconcile_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)

    outcome = remediate_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)

    assert outcome.auto_healed == 0
    assert outcome.blocked >= 1
    row = SettlementRow.objects.get(statement=statement)
    assert row.remediation == SettlementRemediation.BLOCKED
    assert "معیوب" in row.remediation_note


@pytest.mark.django_db
def test_orphan_money_never_heals_automatically(seeded_policies: None) -> None:
    """پول بی‌مالک هرگز نباید خودکار «حل» شود — انسان باید مالک را تعیین کند."""
    del seeded_policies
    admin = _admin("53")
    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=timezone.now() - timedelta(days=1),
        period_end=timezone.now(),
        raw_rows=[{"authority": "SBX-ORPHAN-01", "amount": 9_000_000}],
        actor=admin,
    )
    reconcile_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)

    outcome = remediate_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)

    assert outcome.auto_healed == 0
    row = SettlementRow.objects.get(statement=statement)
    assert row.remediation == SettlementRemediation.QUEUED_REVIEW


# ══════════════════════════════════════════════════════════════════════════════
# ناورداها
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_ledger_stays_balanced_after_auto_heal(seeded_policies: None) -> None:
    """تراز دفتر کل پس از هر خوددرمانی — مهم‌ترین ناوردای مالی."""
    del seeded_policies
    from apps.ledger.services import capture_financial_control_snapshot

    admin = _admin("54")
    campaign = _campaign(admin, slug_suffix="healledger")
    donor = _donor("54")
    contribution = Contribution.objects.create(
        user=donor,
        benefactor=campaign.benefactor,
        target_kind="campaign_shares",
        campaign=campaign,
        shares_count=1,
        amount_rial=1_000_000,
        status=ContributionStatus.PAID,
        hold_expires_at=timezone.now(),
    )
    payment = Payment.objects.create(
        contribution=contribution,
        gateway_name="sandbox",
        authority="SBX-HEALLEDG01",
        amount_rial=1_000_000,
        redirect_url="https://sandbox.invalid/pay",
        status=PaymentStatus.ABANDONED,
    )
    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=timezone.now() - timedelta(days=1),
        period_end=timezone.now(),
        raw_rows=[{"authority": payment.authority, "amount": 1_000_000}],
        actor=admin,
    )
    reconcile_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)
    remediate_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)

    snapshot = capture_financial_control_snapshot(actor=admin)
    assert snapshot.is_balanced is True


@pytest.mark.django_db
def test_every_row_gets_a_verdict(seeded_policies: None) -> None:
    """هیچ ردیفی نباید بی‌نتیجه رها شود — وگرنه حسابرسی ناقص است."""
    del seeded_policies
    admin = _admin("55")
    payment = _verified_payment(admin=admin, suffix="m5", amount=1_000_000)
    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=timezone.now() - timedelta(hours=2),
        period_end=timezone.now() + timedelta(hours=1),
        raw_rows=[
            {"authority": payment.authority, "amount": 1_000_000},  # MATCHED
            {"authority": "SBX-ORPHAN-02", "amount": 2_000_000},  # MISSING_INTERNAL
            {"authority": "SBX-ORPHAN-02", "amount": 2_000_000},  # DUPLICATE
        ],
        actor=admin,
    )
    reconcile_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)

    pending = SettlementRow.objects.filter(
        statement=statement, match_status=SettlementRowMatchStatus.PENDING
    ).count()
    assert pending == 0


@pytest.mark.django_db
def test_statement_reaches_matched_status(seeded_policies: None) -> None:
    """وضعیت سند باید پس از تطبیق واقعی ارتقا یابد."""
    del seeded_policies
    admin = _admin("56")
    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=timezone.now() - timedelta(days=1),
        period_end=timezone.now(),
        raw_rows=[{"authority": "SBX-STATUS-1", "amount": 100_000}],
        actor=admin,
    )
    assert statement.status == SettlementStatementStatus.INGESTED
    reconcile_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)
    statement.refresh_from_db()
    assert statement.status == SettlementStatementStatus.MATCHED


# ══════════════════════════════════════════════════════════════════════════════
# پنل حقیقت وجه و هشدارها — «عدد درست، پیام درست»
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_fresh_system_has_no_truth_alerts(seeded_policies: None) -> None:
    """هشدار کاذب در روز اول، اعتبار کل پنل را از بین می‌برد."""
    del seeded_policies
    from apps.contributions.settlement import build_money_truth_panel, money_truth_alerts

    panel = build_money_truth_panel()
    assert panel["statements_total"] == 0
    assert panel["conflict"] == 0
    assert money_truth_alerts() == []


@pytest.mark.django_db
def test_money_without_any_statement_is_critical(seeded_policies: None) -> None:
    """پول جابه‌جا شده ولی چشم مستقل هرگز باز نشده — این بحرانی است، نه هشدار کاذب."""
    del seeded_policies
    from apps.contributions.settlement import money_truth_alerts

    admin = _admin("57")
    _verified_payment(admin=admin, suffix="m6", amount=1_000_000)

    alerts = money_truth_alerts()
    codes = {a["code"] for a in alerts}
    assert "no_settlement_statement_with_money" in codes
    assert all(a["level"] in {"critical", "warning", "info"} for a in alerts)


@pytest.mark.django_db
def test_stale_statement_is_critical(seeded_policies: None) -> None:
    """سندی که ۴۹ ساعت کهنه است، چشم مستقل را کور می‌کند."""
    del seeded_policies
    from apps.contributions.settlement import money_truth_alerts

    admin = _admin("58")
    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=timezone.now() - timedelta(days=5),
        period_end=timezone.now() - timedelta(days=4),
        raw_rows=[{"authority": "SBX-STALE-01", "amount": 100_000}],
        actor=admin,
    )
    # سند را ۴۹ ساعت به عقب می‌بریم تا «کهنه» شود.
    SettlementStatement.objects.filter(pk=statement.pk).update(
        created_at=timezone.now() - timedelta(hours=49)
    )

    codes = {a["code"] for a in money_truth_alerts()}
    assert "stale_settlement_statement" in codes


@pytest.mark.django_db
def test_panel_separates_confirmed_from_self_reported(seeded_policies: None) -> None:
    """قلب ماجرا: «تأیید خودگواه» و «تأیید مستقل» باید دو عدد جدا باشند."""
    del seeded_policies
    from apps.contributions.settlement import build_money_truth_panel

    admin = _admin("59")
    confirmed = _verified_payment(admin=admin, suffix="m7", amount=1_000_000)
    unconfirmed = _verified_payment(admin=admin, suffix="m8", amount=2_000_000)

    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=timezone.now() - timedelta(hours=2),
        period_end=timezone.now() + timedelta(hours=1),
        raw_rows=[{"authority": confirmed.authority, "amount": 1_000_000}],
        actor=admin,
    )
    reconcile_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)

    panel = build_money_truth_panel()
    assert panel["statement_confirmed"] == 1  # فقط یکی مستقل تأیید شده

    confirmed.refresh_from_db()
    unconfirmed.refresh_from_db()
    assert confirmed.truth_state == PaymentTruthState.STATEMENT_CONFIRMED

    # پرداخت دوم در بازهٔ سند بود ولی در فایل نبود ⇒ ``STATEMENT_MISSING``.
    # این درست است: سند او را «ندید»، پس تأییدش نکرد. نکتهٔ مهم این است که
    # هر دو حالت غیرتأییدشده (UNVERIFIED و STATEMENT_MISSING) در همان سبد
    # «قابل ارائه به هیئت‌مدیره نیست» شمارش می‌شوند — و همین تست آن را قفل می‌کند.
    assert unconfirmed.truth_state in {
        PaymentTruthState.UNVERIFIED,
        PaymentTruthState.STATEMENT_MISSING,
    }
    assert panel["verified_but_unconfirmed"] == 1  # او تنها خودگواهِ باقی‌مانده است
    assert panel["statement_missing"] == 1  # و دقیقاً به همین دلیل
    assert panel["conflict"] == 0  # تناقض قطعی نیست، فقط «تأییدنشده»


@pytest.mark.django_db
def test_metrics_gauge_reflects_truth(seeded_policies: None) -> None:
    """گیج Prometheus باید همان عدد پنل را گزارش کند، نه یک عدد مستقل."""
    del seeded_policies
    from apps.core.metrics import PAYMENTS_TRUTH_CONFIRMED, render_prometheus_metrics

    admin = _admin("60")
    payment = _verified_payment(admin=admin, suffix="m9", amount=1_000_000)

    statement, _, _ = ingest_settlement_statement(
        gateway_name="sandbox",
        source_kind=SettlementSourceKind.CSV,
        period_start=timezone.now() - timedelta(hours=2),
        period_end=timezone.now() + timedelta(hours=1),
        raw_rows=[{"authority": payment.authority, "amount": 1_000_000}],
        actor=admin,
    )
    reconcile_settlement_statement(statement_id=statement.pk, actor=admin, dry_run=False)

    payment.refresh_from_db()
    payload, _ = render_prometheus_metrics()
    text = payload.decode("utf-8")
    assert "crowdfunding_payments_truth_confirmed 1.0" in text
    assert PAYMENTS_TRUTH_CONFIRMED._value.get() == 1


# ══════════════════════════════════════════════════════════════════════════════
# لایهٔ HTTP — مجوز، قرارداد و رفتار
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_ingest_requires_finance_role(seeded_policies: None) -> None:
    """خواندن با کارمند، نوشتن فقط با مدیر مالی — چون ورود سند «حقیقت» می‌سازد."""
    del seeded_policies
    from apps.identity.choices import UserRole
    from apps.identity.models import User
    from tests.conftest import issue_client_for_user

    operator = User.objects.create_user(
        phone="09120009001",
        first_name="اپراتور",
        last_name="پایش",
        role=UserRole.OPERATOR,
        is_staff=True,
    )
    client, _ = issue_client_for_user(operator, mfa_fresh=True)

    # خواندن مجاز است
    assert client.get("/api/v1/admin/settlements").status_code == 200
    # نوشتن ۴۰۳ است
    response = client.post(
        "/api/v1/admin/settlements",
        data={
            "gateway_name": "sandbox",
            "period_start": "2026-11-01T00:00:00Z",
            "period_end": "2026-11-30T00:00:00Z",
            "rows": [{"authority": "SBX-P1", "amount_rial": "1000000"}],
        },
        format="json",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_ingest_returns_201_then_200_for_same_fingerprint(seeded_policies: None) -> None:
    """قرارداد HTTP هم باید idempotency را نشان دهد: ۲۰۱ بار اول، ۲۰۰ بار دوم."""
    del seeded_policies
    from apps.identity.choices import UserRole
    from apps.identity.models import User
    from tests.conftest import issue_client_for_user

    manager = User.objects.create_user(
        phone="09120009002",
        first_name="مدیر",
        last_name="مالی",
        role=UserRole.FINANCE_MANAGER,
        is_staff=True,
    )
    client, _ = issue_client_for_user(manager, mfa_fresh=True)

    body = {
        "gateway_name": "sandbox",
        "source_kind": "manual",
        "period_start": "2026-11-01T00:00:00Z",
        "period_end": "2026-11-30T23:59:59Z",
        "rows": [{"authority": "SBX-HTTP-1", "amount_rial": "۱٬۰۰۰٬۰۰۰"}],
    }
    first = client.post("/api/v1/admin/settlements", data=body, format="json")
    second = client.post("/api/v1/admin/settlements", data=body, format="json")

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    # ارقام فارسی در بدنهٔ HTTP هم درست تفسیر شدند
    assert first.json()["computed_total_rial"] == 1_000_000


@pytest.mark.django_db
def test_reconcile_endpoint_defaults_to_dry_run(seeded_policies: None) -> None:
    """پیش‌فرض بی‌خطر: بدون فرستادن dry_run، هیچ نوشتنی نباید رخ دهد."""
    del seeded_policies
    from apps.identity.choices import UserRole
    from apps.identity.models import User
    from tests.conftest import issue_client_for_user

    manager = User.objects.create_user(
        phone="09120009003",
        first_name="مدیر",
        last_name="مالی۲",
        role=UserRole.FINANCE_MANAGER,
        is_staff=True,
    )
    client, _ = issue_client_for_user(manager, mfa_fresh=True)

    created = client.post(
        "/api/v1/admin/settlements",
        data={
            "gateway_name": "sandbox",
            "period_start": "2026-11-01T00:00:00Z",
            "period_end": "2026-11-30T00:00:00Z",
            "rows": [{"authority": "SBX-DRYRUN-1", "amount_rial": "500000"}],
        },
        format="json",
    ).json()
    statement_id = created["id"]

    # هیچ بدنه‌ای نمی‌فرستیم — باید dry_run بماند
    response = client.post(
        f"/api/v1/admin/settlements/{statement_id}/reconcile", data={}, format="json"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["persisted"] is False


@pytest.mark.django_db
def test_money_truth_panel_endpoint_works_for_operator(seeded_policies: None) -> None:
    """پنل حقیقت باید برای هر کارمندی قابل خواندن باشد."""
    del seeded_policies
    from apps.identity.choices import UserRole
    from apps.identity.models import User
    from tests.conftest import issue_client_for_user

    operator = User.objects.create_user(
        phone="09120009004",
        first_name="اپراتور",
        last_name="پایش۲",
        role=UserRole.OPERATOR,
        is_staff=True,
    )
    client, _ = issue_client_for_user(operator, mfa_fresh=True)

    response = client.get("/api/v1/admin/money-truth")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) >= {
        "verified_but_unconfirmed",
        "statement_confirmed",
        "conflict",
        "unresolved_impact_rial",
    }


@pytest.mark.django_db
def test_settlement_detail_reports_match_status_counts(seeded_policies: None) -> None:
    """جزئیات سند باید شمارش هر وضعیت را بدهد تا اپراتور بداند کجا را ببیند."""
    del seeded_policies
    from apps.identity.choices import UserRole
    from apps.identity.models import User
    from tests.conftest import issue_client_for_user

    manager = User.objects.create_user(
        phone="09120009005",
        first_name="مدیر",
        last_name="مالی۳",
        role=UserRole.FINANCE_MANAGER,
        is_staff=True,
    )
    client, _ = issue_client_for_user(manager, mfa_fresh=True)

    created = client.post(
        "/api/v1/admin/settlements",
        data={
            "gateway_name": "sandbox",
            "period_start": "2026-11-01T00:00:00Z",
            "period_end": "2026-11-30T00:00:00Z",
            "rows": [
                {"authority": "SBX-D-1", "amount_rial": "100000"},
                {"authority": "SBX-D-1", "amount_rial": "100000"},
            ],
        },
        format="json",
    ).json()

    client.post(
        f"/api/v1/admin/settlements/{created['id']}/reconcile",
        data={"dry_run": False},
        format="json",
    )
    detail = client.get(f"/api/v1/admin/settlements/{created['id']}")

    assert detail.status_code == 200
    counts = detail.json()["match_status_counts"]
    assert counts.get("duplicate_in_file", 0) >= 1
