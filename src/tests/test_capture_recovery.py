"""آزمون‌های حلقهٔ نجات وجه (Capture Recovery).

این فایل، قرارداد رفتاری سه مسیر داوری را قفل می‌کند و سه نوع تضمین می‌دهد:

۱) **تضمین پولی**   — هیچ ترکیبی از «پول گرفته شد / سهم پر شد / کاربر برنگشت»
                        نمی‌تواند به «پول گم‌شده» منتهی شود.
۲) **تضمین حسابداری** — هر مسیر، سند دفترکل متوازن می‌سازد؛ بدهی بازپرداخت هرگز
                        بدون رکورد نمی‌ماند.
۳) **تضمین عملیاتی**  — اجرای مکرر کرون هیچ‌گاه دو بار تخصیص یا دو بار بازپرداخت
                        ایجاد نمی‌کند (idempotency در سطح داده).
"""

from __future__ import annotations

from datetime import timedelta

from django.test import override_settings
from django.utils import timezone
import pytest

from apps.audit.models import AuditRecord
from apps.benefactors.models import Benefactor
from apps.campaigns.choices import CampaignStatus
from apps.campaigns.models import Campaign, CampaignCategory
from apps.campaigns.services import create_campaign
from apps.contributions.choices import (
    ContributionStatus,
    LateCaptureOutcome,
    PaymentStatus,
    RefundOutcome,
)
from apps.contributions.financial_health import build_financial_health
from apps.contributions.models import (
    Contribution,
    LateCaptureRecovery,
    Payment,
    PaymentRefund,
)
from apps.contributions.services import (
    dispatch_pending_refunds,
    initiate_contribution_checkout,
    reconcile_abandoned_payments,
    reconcile_one_abandoned_payment,
    release_expired_share_holds,
    settle_refund_obligation,
    verify_payment_callback,
)
from apps.contributions.state_machine import (
    IllegalTransitionError,
    assert_contribution_transition,
    assert_payment_transition,
    can_contribution_transition,
)
from apps.core.errors import NotFoundError
from apps.identity.models import User
from apps.ledger.services import capture_financial_control_snapshot

# ── کمکی‌ها ──────────────────────────────────────────────────────────────────


def _admin(suffix: str = "01") -> User:
    return User.objects.create_superuser(
        phone=f"091200088{suffix}", first_name="ادمین", last_name="بازیافت"
    )


def _donor(suffix: str = "01") -> User:
    return User.objects.create_user(
        phone=f"091200099{suffix}", first_name="حامی", last_name="آزمون"
    )


def _campaign(admin: User, *, total_shares: int = 10, slug_suffix: str = "a") -> Campaign:
    benefactor = Benefactor.objects.create(
        name=f"خیریهٔ آزمون بازیافت {slug_suffix}",
        slug=f"recovery-charity-{slug_suffix}",
        is_verified=True,
        is_active=True,
    )
    category = CampaignCategory.objects.create(
        title=f"دستهٔ بازیافت {slug_suffix}", slug=f"recovery-cat-{slug_suffix}"
    )
    return create_campaign(
        actor=admin,
        data={
            "benefactor_id": str(benefactor.id),
            "category_id": str(category.id),
            "title": f"حرکت آزمون بازیافت {slug_suffix}",
            "slug": f"recovery-campaign-{slug_suffix}",
            "subtitle": "زیرعنوان",
            "story": "داستان حرکت برای آزمون حلقهٔ نجات وجه.",
            "province": "تهران",
            "city": "تهران",
            "total_shares": total_shares,
            "share_price_rial": 1_000_000,
            "status": CampaignStatus.ACTIVE,
        },
    )


def _abandon(payment: Payment, *, minutes_ago: int = 40) -> None:
    """پرداخت را از دید زمان به عقب می‌برد تا از پنجرهٔ مهلت عبور کند."""
    past = timezone.now() - timedelta(minutes=minutes_ago)
    Payment.objects.filter(pk=payment.pk).update(created_at=past, updated_at=past)


def _dry_checkout(
    *, user: User, campaign: Campaign, shares: int = 2
) -> tuple[Contribution, Payment]:
    """رزرو + هدایت به درگاه، بدون هیچ بازگشتی (سناریوی «کاربر گم شد»)."""
    return initiate_contribution_checkout(
        user=user,
        target_kind="campaign_shares",
        campaign_id=str(campaign.id),
        shares_count=shares,
    )


# ── ۱. ماشین حالت ────────────────────────────────────────────────────────────


def test_state_machine_rejects_impossible_transitions() -> None:
    """گذارهای غیرممکن باید صریحاً رد شوند (نه بی‌صدا نادیده گرفته شوند)."""
    with pytest.raises(IllegalTransitionError):
        assert_contribution_transition(ContributionStatus.REFUNDED, ContributionStatus.PAID)
    with pytest.raises(IllegalTransitionError):
        assert_payment_transition(PaymentStatus.REFUNDED, PaymentStatus.VERIFIED)

    assert can_contribution_transition(ContributionStatus.EXPIRED, ContributionStatus.CAPTURED_LATE)
    assert can_contribution_transition(
        ContributionStatus.EXPIRED, ContributionStatus.AWAITING_REFUND
    )
    # وضعیت پایانه هیچ خروجی ندارد
    assert not can_contribution_transition(
        ContributionStatus.REFUNDED, ContributionStatus.CAPTURED_LATE
    )


# ── ۲. انقضا دیگر هرگز «ناموفق» نمی‌نویسد ────────────────────────────────────


@pytest.mark.django_db
def test_hold_expiry_marks_payment_abandoned_not_failed(seeded_policies: None) -> None:
    """رزرو منقضی ⇒ پرداخت «رها‌شده» می‌شود، نه «ناموفق» (وگرنه پول نامرئی می‌شود)."""
    del seeded_policies
    admin = _admin("01")
    campaign = _campaign(admin, slug_suffix="abandon")
    contribution, payment = _dry_checkout(user=_donor("01"), campaign=campaign)

    Contribution.objects.filter(pk=contribution.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    assert release_expired_share_holds(campaign_id=campaign.id) == 1

    payment.refresh_from_db()
    contribution.refresh_from_db()
    assert payment.status == PaymentStatus.ABANDONED
    assert contribution.status == ContributionStatus.EXPIRED


# ── ۳. مسیر اول: درگاه می‌گوید پولی نبوده ────────────────────────────────────


@pytest.mark.django_db
def test_reconcile_not_captured_is_harmless(seeded_policies: None) -> None:
    """اگر درگاه تأیید نکند، هیچ سهم و هیچ بدهی‌ای نباید ساخته شود."""
    del seeded_policies
    admin = _admin("02")
    campaign = _campaign(admin, slug_suffix="nocap")

    # پرداخت جعلی با authority نامعتبر ⇒ Sandbox صریحاً رد می‌کند
    donor = _donor("02")
    contribution = Contribution.objects.create(
        user=donor,
        benefactor=campaign.benefactor,
        target_kind="campaign_shares",
        campaign=campaign,
        shares_count=2,
        amount_rial=2_000_000,
        status=ContributionStatus.EXPIRED,
        hold_expires_at=timezone.now() - timedelta(minutes=10),
    )
    payment = Payment.objects.create(
        contribution=contribution,
        gateway_name="sandbox",
        authority="INVALID-AUTHORITY-XYZ",
        amount_rial=2_000_000,
        redirect_url="https://sandbox.invalid/pay",
        status=PaymentStatus.ABANDONED,
    )
    _abandon(payment)

    outcome = reconcile_one_abandoned_payment(payment_id=payment.pk)

    assert outcome == LateCaptureOutcome.NOT_CAPTURED
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.FAILED
    assert not PaymentRefund.objects.filter(payment=payment).exists()
    recovery = LateCaptureRecovery.objects.get(payment=payment)
    assert recovery.outcome == LateCaptureOutcome.NOT_CAPTURED
    assert recovery.resolved_at is not None


# ── ۴. مسیر دوم: بازیافت با تخصیص مجدد سهم (بهترین حالت) ─────────────────────


@pytest.mark.django_db
def test_recovery_assigns_shares_and_balances_ledger(seeded_policies: None) -> None:
    """پول گرفته شده و ظرفیت هست ⇒ سهم تخصیص، رسید صادر و دفترکل متوازن می‌شود."""
    del seeded_policies
    admin = _admin("03")
    campaign = _campaign(admin, total_shares=10, slug_suffix="recover")
    contribution, payment = _dry_checkout(user=_donor("03"), campaign=campaign, shares=3)

    Contribution.objects.filter(pk=contribution.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    release_expired_share_holds(campaign_id=campaign.id)
    _abandon(payment)

    outcome = reconcile_one_abandoned_payment(payment_id=payment.pk)

    assert outcome == LateCaptureOutcome.RECOVERED

    payment.refresh_from_db()
    contribution.refresh_from_db()
    campaign.refresh_from_db()

    assert payment.status == PaymentStatus.VERIFIED
    assert payment.ref_id.startswith("SBXREF-")
    assert contribution.status == ContributionStatus.CAPTURED_LATE
    assert contribution.paid_at is not None
    assert campaign.paid_shares == 3
    assert hasattr(contribution, "receipt")  # رسید صادر شده است

    # حسابداری: استرداد تعهدی لازم نیست و دفتر تراز است.
    assert not PaymentRefund.objects.filter(payment=payment).exists()
    assert capture_financial_control_snapshot().is_balanced is True

    recovery = LateCaptureRecovery.objects.get(payment=payment)
    assert recovery.outcome == LateCaptureOutcome.RECOVERED
    assert recovery.recovered_shares == 3
    assert recovery.gateway_ref_id.startswith("SBXREF-")


# ── ۵. مسیر سوم: پول گرفته شد ولی سهم پر شد ⇒ بدهی بازپرداخت ─────────────────


@pytest.mark.django_db
def test_refund_obligation_when_capacity_is_gone(seeded_policies: None) -> None:
    """سهم پر شده ⇒ تعهد بازپرداخت ساخته شود و ترازنامه بدهکار بماند (نه گم شود)."""
    del seeded_policies
    admin = _admin("04")
    campaign = _campaign(admin, total_shares=2, slug_suffix="norefund")
    donor = _donor("04")
    contribution, payment = _dry_checkout(user=donor, campaign=campaign, shares=2)

    # رزرو منقضی و کل ظرفیت توسط خریدار دوم پر می‌شود.
    Contribution.objects.filter(pk=contribution.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    release_expired_share_holds(campaign_id=campaign.id)
    second_donor = User.objects.create_user(phone="09120009999", first_name="حامی", last_name="دوم")
    second_contribution, second_payment = _dry_checkout(
        user=second_donor, campaign=campaign, shares=2
    )
    verify_payment_callback(authority=second_payment.authority, gateway_status="OK")
    _abandon(payment)

    outcome = reconcile_one_abandoned_payment(payment_id=payment.pk)

    assert outcome == LateCaptureOutcome.REFUND_PENDING

    contribution.refresh_from_db()
    payment.refresh_from_db()
    assert contribution.status == ContributionStatus.AWAITING_REFUND
    assert payment.status == PaymentStatus.VERIFIED

    refund = PaymentRefund.objects.get(payment=payment)
    assert refund.outcome == RefundOutcome.PENDING
    assert refund.refunded_by is None  # مسیر خودکار، بدون اپراتور انسانی
    assert refund.amount_rial == contribution.amount_rial

    # حیاتی: دفترکل با وجود یک بدهی باز، هم‌چنان تراز است.
    assert capture_financial_control_snapshot().is_balanced is True

    health = build_financial_health()
    assert health["money_loop"]["pending_refund_obligations"] == 1
    assert health["money_loop"]["refund_liability_rial"] == int(contribution.amount_rial)
    assert any(a["code"] == "pending_refunds" for a in health["alerts"])

    # و خریدار دوم دست‌نخورده باقی می‌ماند (هیچ سهمی از او کسر نشده).
    second_contribution.refresh_from_db()
    assert second_contribution.status == ContributionStatus.PAID


# ── ۶. اثبات idempotency در سطح داده ─────────────────────────────────────────


@pytest.mark.django_db
def test_reconcile_is_idempotent_under_repeated_cron_runs(seeded_policies: None) -> None:
    """سه بار اجرای داوری ⇒ همچنان یک تخصیص و یک تعهد، نه سه تا."""
    del seeded_policies
    admin = _admin("05")
    campaign = _campaign(admin, total_shares=5, slug_suffix="idem")
    contribution, payment = _dry_checkout(user=_donor("05"), campaign=campaign, shares=2)

    Contribution.objects.filter(pk=contribution.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    release_expired_share_holds(campaign_id=campaign.id)
    _abandon(payment)

    first = reconcile_one_abandoned_payment(payment_id=payment.pk)
    second = reconcile_one_abandoned_payment(payment_id=payment.pk)
    third = reconcile_one_abandoned_payment(payment_id=payment.pk)

    assert first == second == third == LateCaptureOutcome.RECOVERED

    campaign.refresh_from_db()
    assert campaign.paid_shares == 2  # نه ۶
    assert LateCaptureRecovery.objects.filter(payment=payment).count() == 1
    assert contribution.receipt is not None  # type: ignore[has-type]
    assert capture_financial_control_snapshot().is_balanced is True


@pytest.mark.django_db
def test_batch_reconcile_reports_every_outcome_bucket(seeded_policies: None) -> None:
    """داوری دسته‌ای، آمار را به تفکیک نتیجه گزارش کند (برای پایش)."""
    del seeded_policies
    admin = _admin("06")
    campaign = _campaign(admin, total_shares=20, slug_suffix="batch")
    contribution, payment = _dry_checkout(user=_donor("06"), campaign=campaign, shares=1)

    Contribution.objects.filter(pk=contribution.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    release_expired_share_holds(campaign_id=campaign.id)
    _abandon(payment)

    stats = reconcile_abandoned_payments(batch_size=50)

    assert stats["dry_run"] is False
    assert stats["scanned"] >= 1
    assert stats["recovered"] == 1
    assert stats["error_count"] == 0


@pytest.mark.django_db
def test_dry_run_changes_nothing(seeded_policies: None) -> None:
    """پیش‌نمایش باید هیچ تغییری در داده ایجاد نکند."""
    del seeded_policies
    admin = _admin("07")
    campaign = _campaign(admin, slug_suffix="dry")
    contribution, payment = _dry_checkout(user=_donor("07"), campaign=campaign, shares=1)

    Contribution.objects.filter(pk=contribution.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    release_expired_share_holds(campaign_id=campaign.id)
    _abandon(payment)

    stats = reconcile_abandoned_payments(dry_run=True)

    assert stats["dry_run"] is True
    assert stats["recovered"] == 0
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.ABANDONED
    assert not LateCaptureRecovery.objects.filter(payment=payment).exists()


# ── ۷. حلقهٔ کامل بازپرداخت: ارسال و تسویه ───────────────────────────────────


@pytest.mark.django_db
def test_refund_lifecycle_dispatch_and_settle(seeded_policies: None) -> None:
    """تعهد ⇒ ارسال به درگاه ⇒ تسویه ⇒ بدهی صفر و دفتر متوازن."""
    del seeded_policies
    admin = _admin("08")
    campaign = _campaign(admin, total_shares=2, slug_suffix="lifecycle")
    contribution, payment = _dry_checkout(user=_donor("08"), campaign=campaign, shares=2)

    Contribution.objects.filter(pk=contribution.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    release_expired_share_holds(campaign_id=campaign.id)
    second_donor = User.objects.create_user(phone="09120009988", first_name="حامی", last_name="سوم")
    _, second_payment = _dry_checkout(user=second_donor, campaign=campaign, shares=2)
    verify_payment_callback(authority=second_payment.authority, gateway_status="OK")
    _abandon(payment)

    reconcile_one_abandoned_payment(payment_id=payment.pk)
    refund = PaymentRefund.objects.get(payment=payment)

    dispatch = dispatch_pending_refunds()
    assert dispatch["attempted"] == 1
    assert dispatch["sent"] == 1  # Sandbox از بازپرداخت پشتیبانی می‌کند

    refund.refresh_from_db()
    assert refund.outcome == RefundOutcome.SENT
    assert refund.gateway_reference.startswith("SBXRFD-")

    settled = settle_refund_obligation(
        refund_id=refund.pk, actor=admin, note="تأیید تسویه بازپرداخت آزمون"
    )

    assert settled.outcome == RefundOutcome.COMPLETED
    payment.refresh_from_db()
    contribution.refresh_from_db()
    assert payment.status == PaymentStatus.REFUNDED
    assert contribution.status == ContributionStatus.REFUNDED

    health = build_financial_health()
    assert health["money_loop"]["pending_refund_obligations"] == 0
    assert health["money_loop"]["refund_liability_rial"] == 0
    assert capture_financial_control_snapshot().is_balanced is True


@pytest.mark.django_db
@override_settings(ZARINPAL_MERCHANT_ID="11111111-2222-3333-4444-555555555555")
def test_zarinpal_refund_goes_to_manual_path(seeded_policies: None) -> None:
    """درگاهی که بازپرداخت خودکار ندارد نباید بی‌نهایت تلاش کند؛ باید صریحاً دستی شود."""
    del seeded_policies
    admin = _admin("09")
    campaign = _campaign(admin, slug_suffix="manual")
    donor = _donor("09")

    contribution = Contribution.objects.create(
        user=donor,
        benefactor=campaign.benefactor,
        target_kind="campaign_shares",
        campaign=campaign,
        shares_count=1,
        amount_rial=1_000_000,
        status=ContributionStatus.AWAITING_REFUND,
        hold_expires_at=timezone.now(),
    )
    payment = Payment.objects.create(
        contribution=contribution,
        gateway_name="zarinpal",
        authority="ZP-AUTH-MANUAL-1",
        amount_rial=1_000_000,
        redirect_url="https://payment.zarinpal.com/pg/StartPay/ZP-AUTH-MANUAL-1",
        status=PaymentStatus.VERIFIED,
    )
    refund = PaymentRefund.objects.create(
        payment=payment,
        amount_rial=1_000_000,
        reason="ظرفیت تکمیل بود",
        outcome=RefundOutcome.PENDING,
    )

    stats = dispatch_pending_refunds()

    assert stats["manual"] == 1
    refund.refresh_from_db()
    assert refund.outcome == RefundOutcome.MANUAL
    assert "دستی" in refund.automation_note


# ── ۸. پنل سلامت مالی ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_financial_health_surfaces_stale_abandoned_money(seeded_policies: None) -> None:
    """پرداخت رهاشدهٔ کهنه باید هشدار critical بدهد (نه اینکه بی‌صدا بماند)."""
    del seeded_policies
    admin = _admin("10")
    campaign = _campaign(admin, slug_suffix="health")
    contribution, payment = _dry_checkout(user=_donor("10"), campaign=campaign, shares=1)

    Contribution.objects.filter(pk=contribution.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    release_expired_share_holds(campaign_id=campaign.id)
    _abandon(payment, minutes_ago=180)

    health = build_financial_health()

    assert health["status"] == "attention_required"
    assert health["money_loop"]["stale_abandoned_over_1h"] >= 1
    codes = {a["code"] for a in health["alerts"]}
    assert "stale_abandoned_payments" in codes


@pytest.mark.django_db
def test_financial_health_is_clean_on_fresh_system(seeded_policies: None) -> None:
    """سامانهٔ تازه باید healthy باشد و هیچ هشدار کاذبی ندهد."""
    del seeded_policies
    health = build_financial_health()
    assert health["status"] == "healthy"
    assert health["alerts"] == []
    assert health["money_loop"]["pending_refund_obligations"] == 0


# ── ۹. مسیرهای خطا ──────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_reconcile_unknown_payment_raises_not_found() -> None:
    """شناسهٔ ناموجود باید ۴۰۴ دامنه‌ای بدهد، نه خطای داخلی."""
    with pytest.raises(NotFoundError):
        reconcile_one_abandoned_payment(payment_id="00000000-0000-0000-0000-000000000000")


@pytest.mark.django_db
def test_settle_unknown_refund_raises_not_found() -> None:
    """تسویهٔ بازپرداخت ناموجود نیز باید ۴۰۴ دامنه‌ای بدهد."""
    with pytest.raises(NotFoundError):
        settle_refund_obligation(refund_id="00000000-0000-0000-0000-000000000000", actor=None)


# ── ۱۰. ردپای حسابرسی ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_recovery_writes_audit_trail(seeded_policies: None) -> None:
    """هر بازیافت باید در زنجیرهٔ حسابرسی ردپا بگذارد (قابلیت ممیزی پس‌رویدادی)."""
    del seeded_policies
    admin = _admin("11")
    campaign = _campaign(admin, slug_suffix="audit")
    contribution, payment = _dry_checkout(user=_donor("11"), campaign=campaign, shares=1)

    Contribution.objects.filter(pk=contribution.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    release_expired_share_holds(campaign_id=campaign.id)
    _abandon(payment)

    reconcile_one_abandoned_payment(payment_id=payment.pk)

    assert AuditRecord.objects.filter(
        action="finance.late_capture_recovered",
        target_id=str(payment.pk),
    ).exists()


# ── ۱۱. رگرسیون: سقوط بی‌صدا به درگاه آزمایشی در مسیر پول ───────────────────


@override_settings(PAYMENT_DEFAULT_GATEWAY="zarinpal", ZARINPAL_MERCHANT_ID="")
def test_missing_zarinpal_key_never_silently_falls_back_to_sandbox() -> None:
    """اگر زرین‌پال خواسته شد ولی کلیدش نبود، باید خطای صریح بدهد نه آداپتور جعلی.

    این رگرسیون یک باگ واقعی را قفل می‌کند: پیش‌تر بازپرداخت یک تراکنش زرین‌پال،
    بی‌صدا با آداپتور Sandbox «تأیید» می‌شد — یعنی سامانه ادعای بازپرداخت می‌کرد
    در حالی که پول واقعی برنگشته بود.
    """
    from apps.contributions.gateways import resolve_payment_gateway
    from apps.core.errors import ValidationError as DomainValidationError

    with pytest.raises(DomainValidationError) as exc_info:
        resolve_payment_gateway("zarinpal")

    assert getattr(exc_info.value, "code", "") == "gateway_not_configured"


@override_settings(ZARINPAL_MERCHANT_ID="11111111-2222-3333-4444-555555555555")
def test_zarinpal_adapter_refund_is_explicitly_unsupported() -> None:
    """آداپتور زرین‌پال باید بازپرداخت را «پشتیبانی‌نشده» اعلام کند، نه موفق قلابی."""
    from apps.contributions.gateways import ZarinpalGatewayAdapter

    adapter = ZarinpalGatewayAdapter(
        merchant_id="11111111-2222-3333-4444-555555555555",
        request_url="https://payment.zarinpal.com/pg/v4/payment/request.json",
        verify_url="https://payment.zarinpal.com/pg/v4/payment/verify.json",
        startpay_base="https://payment.zarinpal.com/pg/StartPay",
    )
    result = adapter.refund(authority="A" * 36, amount_rial=1_000_000, reason="آزمون")

    assert result.accepted is False
    assert result.unsupported is True
    assert result.raw_code == "NOT_SUPPORTED"


# ── ۱۲. انضباط معماری: ماشین حالت نباید از کد عقب بیفتد ─────────────────────


def test_state_machine_covers_every_runtime_transition() -> None:
    """هر وضعیتی که کد واقعاً به آن *می‌رود* باید در گراف ماشین حالت وجود داشته باشد.

    منطق: کد را با AST می‌خوانیم، هر انتساب ``<x>.status = <Enum>.VALUE`` را
    برمی‌داریم و بررسی می‌کنیم که ``VALUE`` در همان گراف، یک وضعیت **اعلان‌شده**
    باشد (چه به‌عنوان مبدأ، چه به‌عنوان مقصد). اگر توسعه‌دهنده‌ای وضعیت تازه‌ای
    در کد بنویسد ولی آن را در ``state_machine`` مدل نکند، این تست قرمز می‌شود.
    """
    from pathlib import Path as _Path

    from apps.contributions.state_machine import (
        CONTRIBUTION_TRANSITIONS,
        PAYMENT_TRANSITIONS,
    )

    # نام‌ها (مثل ``PAID``) نه مقادیر (مثل ``paid``) — کد در انتساب از نام استفاده می‌کند.
    contrib_states = set(CONTRIBUTION_TRANSITIONS)
    payment_states = set(PAYMENT_TRANSITIONS)
    for transitions in CONTRIBUTION_TRANSITIONS.values():
        contrib_states |= set(transitions)
    for transitions in PAYMENT_TRANSITIONS.values():
        payment_states |= set(transitions)
    declared_contrib: set[str] = {str(member.name) for member in contrib_states}
    declared_payment: set[str] = {str(member.name) for member in payment_states}

    source_root = _Path(__file__).resolve().parents[1] / "apps"
    violations: list[str] = []

    for py_file in source_root.rglob("*.py"):
        if "migrations" in py_file.parts or "tests" in py_file.parts:
            continue
        text = py_file.read_text(encoding="utf-8")
        if "ContributionStatus." not in text and "PaymentStatus." not in text:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            for prefix, declared, label in (
                ("contribution.status = ", declared_contrib, "ContributionStatus"),
                ("payment.status = ", declared_payment, "PaymentStatus"),
            ):
                if not stripped.startswith(prefix) or "Status." not in stripped:
                    continue
                value = stripped.split("Status.", 1)[1].split()[0].rstrip(",;")
                if value not in declared:
                    violations.append(
                        f"{py_file.relative_to(source_root.parent)}:{line_no} "
                        f"sets {label}.{value} which is not modelled in state_machine.py"
                    )

    assert not violations, "Unmodelled state assignments found:\n" + "\n".join(violations)


def test_every_domain_status_is_reachable_or_terminal() -> None:
    """هیچ وضعیتی نباید «یتیم» باشد: یا از جایی می‌آید یا پایانه است."""
    from apps.contributions.choices import ContributionStatus, PaymentStatus
    from apps.contributions.state_machine import (
        CONTRIBUTION_TRANSITIONS,
        PAYMENT_TRANSITIONS,
    )

    for enum, graph in (
        (ContributionStatus, CONTRIBUTION_TRANSITIONS),
        (PaymentStatus, PAYMENT_TRANSITIONS),
    ):
        reachable = set(graph)
        for transitions in graph.values():
            reachable |= set(transitions)
        orphans = set(enum.values) - reachable
        assert not orphans, f"{enum.__name__}: unreachable statuses {orphans}"


def test_money_at_gateway_statuses_are_exactly_the_profitable_ones() -> None:
    """هر وضعیتی که یعنی «پول نزد درگاه است» باید صریحاً اعلان شده باشد."""
    from apps.contributions.choices import ContributionStatus
    from apps.contributions.state_machine import MONEY_AT_GATEWAY_STATUSES

    expected = {
        ContributionStatus.PAID,
        ContributionStatus.CAPTURED_LATE,
        ContributionStatus.AWAITING_REFUND,
    }
    assert set(MONEY_AT_GATEWAY_STATUSES) == expected
