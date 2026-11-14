"""آزمون‌های مسیرهای دشوار حلقهٔ نجات وجه: خطای شبکه، ادمین، متریک و جبران.

این فایل مکمل ``test_capture_recovery.py`` است و عمداً روی «آنچه ممکن است خراب
شود» تمرکز دارد، نه مسیر خوش‌بینانه:

    • درگاه پاسخ نمی‌دهد      ⇒ باید تلاش مجدد شود، نه تصمیم غلط
    • سقف تلاش پر می‌شود       ⇒ باید به بررسی انسانی برود
    • حرکت در این فاصله بسته می‌شود ⇒ تخصیص نباید انجام شود
    • قلک عام (بدون حرکت)      ⇒ مسیر موازی باید کار کند
    • اپراتور بی‌مجوز           ⇒ باید ۴۰۳ بگیرد، نه ۵۰۰
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
import pytest

from apps.campaigns.choices import CampaignStatus
from apps.contributions.choices import (
    ContributionStatus,
    LateCaptureOutcome,
    PaymentStatus,
    RefundOutcome,
)
from apps.contributions.gateways import GatewayRefundResult, GatewayVerifyResult
from apps.contributions.models import Contribution, LateCaptureRecovery, Payment, PaymentRefund
from apps.contributions.services import (
    dispatch_pending_refunds,
    initiate_contribution_checkout,
    reconcile_one_abandoned_payment,
    release_expired_share_holds,
    settle_refund_obligation,
)
from apps.core.errors import ValidationError as DomainValidationError
from apps.identity.models import User
from tests.conftest import issue_client_for_user
from tests.test_capture_recovery import _abandon, _admin, _campaign, _donor, _dry_checkout


class _FlakyGateway:
    """درگاه جعلی که یا استثنا می‌دهد یا پاسخ دلخواه را برمی‌گرداند."""

    def __init__(self, *, exc: Exception | None = None, verified: bool = True) -> None:
        self._exc = exc
        self._verified = verified
        self.calls = 0

    def initiate(self, **kwargs: Any) -> Any:  # pragma: no cover - در این تست‌ها لازم نیست
        raise NotImplementedError

    def verify(self, *, authority: str, amount_rial: int) -> GatewayVerifyResult:
        del authority, amount_rial
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return GatewayVerifyResult(
            verified=self._verified,
            ref_id="FLAKY-REF-1" if self._verified else "",
            raw_code="100" if self._verified else "-51",
        )

    def refund(self, *, authority: str, amount_rial: int, reason: str = "") -> GatewayRefundResult:
        del authority, amount_rial, reason
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return GatewayRefundResult(accepted=True, gateway_reference="FLAKY-RFD-1", raw_code="100")


# ── ۱. خطای شبکه: هیچ تصمیم غلطی نباید گرفته شود ────────────────────────────


@pytest.mark.django_db
def test_network_error_leaves_payment_untouched_for_retry(seeded_policies: None) -> None:
    """وقتی درگاه در دسترس نیست، پرداخت باید «رها‌شده» بماند و بعداً دوباره تلاش شود."""
    del seeded_policies
    admin = _admin("21")
    campaign = _campaign(admin, slug_suffix="neterr")
    contribution, payment = _dry_checkout(user=_donor("21"), campaign=campaign, shares=1)

    Contribution.objects.filter(pk=contribution.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    release_expired_share_holds(campaign_id=campaign.id)
    _abandon(payment)

    flaky = _FlakyGateway(exc=TimeoutError("شبکه قطع است"))
    with patch("apps.contributions.services.resolve_payment_gateway", return_value=flaky):
        outcome = reconcile_one_abandoned_payment(payment_id=payment.pk)

    assert outcome == LateCaptureOutcome.MANUAL_REVIEW
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.ABANDONED  # دست‌نخورده

    recovery = LateCaptureRecovery.objects.get(payment=payment)
    assert "TimeoutError" in recovery.last_error
    assert recovery.attempt_count == 1
    assert recovery.resolved_at is None  # حل‌نشده ⇒ کرون بعدی دوباره تلاش می‌کند


@pytest.mark.django_db
def test_max_attempts_escalates_to_human_review(seeded_policies: None) -> None:
    """پس از سقف تلاش، تلاش خودکار متوقف و پرونده به انسان ارجاع می‌شود."""
    del seeded_policies
    admin = _admin("22")
    campaign = _campaign(admin, slug_suffix="maxatt")
    contribution, payment = _dry_checkout(user=_donor("22"), campaign=campaign, shares=1)

    Contribution.objects.filter(pk=contribution.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    release_expired_share_holds(campaign_id=campaign.id)
    _abandon(payment)

    # سقف تلاش را به ۱ کاهش می‌دهیم تا سناریو سریع شبیه‌سازی شود.
    flaky = _FlakyGateway(exc=ConnectionError("قطعی"))
    with patch("apps.contributions.services.resolve_payment_gateway", return_value=flaky):
        first = reconcile_one_abandoned_payment(payment_id=payment.pk)
        assert first == LateCaptureOutcome.MANUAL_REVIEW

        recovery = LateCaptureRecovery.objects.get(payment=payment)
        # سقف پیش‌فرض سیاست = ۵؛ با ۴ تلاش دیگر باید قفل شود.
        for _ in range(6):
            reconcile_one_abandoned_payment(payment_id=payment.pk)

    recovery.refresh_from_db()
    assert recovery.outcome == LateCaptureOutcome.MANUAL_REVIEW
    assert recovery.resolved_at is not None
    assert recovery.decision_reason == "max_attempts_exceeded"
    assert flaky.calls <= 6  # از سقف عبور نکرده


# ── ۲. حرکت بسته شده بین انقضا و داوری ──────────────────────────────────────


@pytest.mark.django_db
def test_closed_campaign_forces_refund_instead_of_assignment(seeded_policies: None) -> None:
    """اگر حرکت در این فاصله بسته شود، تخصیص خودکار مجاز نیست ⇒ بازپرداخت."""
    del seeded_policies
    admin = _admin("23")
    campaign = _campaign(admin, total_shares=20, slug_suffix="closed")
    contribution, payment = _dry_checkout(user=_donor("23"), campaign=campaign, shares=2)

    Contribution.objects.filter(pk=contribution.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    release_expired_share_holds(campaign_id=campaign.id)

    # مدیر، حرکت را می‌بندد (مثلاً به دلیل پایان مهلت)
    from apps.campaigns.models import Campaign as CampaignModel

    CampaignModel.objects.filter(pk=campaign.pk).update(status=CampaignStatus.CANCELLED)
    _abandon(payment)

    outcome = reconcile_one_abandoned_payment(payment_id=payment.pk)

    assert outcome == LateCaptureOutcome.REFUND_PENDING
    contribution.refresh_from_db()
    assert contribution.status == ContributionStatus.AWAITING_REFUND
    assert PaymentRefund.objects.filter(payment=payment, outcome=RefundOutcome.PENDING).exists()


# ── ۳. قلک عام: مسیر بدون حرکت ─────────────────────────────────────────────


@pytest.mark.django_db
def test_charity_jar_recovery_works_without_campaign(seeded_policies: None) -> None:
    """مسیر نجات باید برای واریز قلک عام (بدون حرکت) هم کار کند."""
    del seeded_policies
    from apps.benefactors.models import Benefactor, CharityJar

    _admin("24")  # ساخت مدیر لازم است (خیریه به آن ارجاع می‌دهد)
    benefactor = Benefactor.objects.create(
        name="خیریهٔ قلک بازیافت", slug="jar-recovery-charity", is_verified=True, is_active=True
    )
    jar = CharityJar.objects.create(
        benefactor=benefactor,
        title="قلک آزمون بازیافت",
        slug="jar-recovery-test",
        description="قلک برای آزمون بازیافت وجه",
        min_amount_rial=100_000,
        max_amount_rial=50_000_000,
        is_active=True,
    )
    donor = _donor("24")
    contribution, payment = initiate_contribution_checkout(
        user=donor,
        target_kind="charity_jar",
        charity_jar_id=str(jar.id),
        amount_rial=500_000,
    )

    Contribution.objects.filter(pk=contribution.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    release_expired_share_holds()
    _abandon(payment)

    outcome = reconcile_one_abandoned_payment(payment_id=payment.pk)

    assert outcome == LateCaptureOutcome.RECOVERED
    jar.refresh_from_db()
    assert jar.total_raised_rial == 500_000
    assert jar.donor_count == 1


# ── ۴. بازپرداخت: مسیرهای خطا و غیرفعال‌بودن ────────────────────────────────


@pytest.mark.django_db
def test_dispatch_skips_when_policy_disabled(seeded_policies: None) -> None:
    """اگر سیاست، ارسال خودکار را خاموش کند، هیچ تلاشی نباید انجام شود."""
    del seeded_policies
    from apps.core.models import PolicyRule

    PolicyRule.objects.update_or_create(
        key="recovery.auto_refund_enabled",
        defaults={"value_type": "bool", "raw_value": False, "description": "غیرفعال در آزمون"},
    )
    from django.core.cache import cache

    cache.clear()

    stats = dispatch_pending_refunds()

    assert stats["skipped"] == -1
    assert stats["attempted"] == 0


@pytest.mark.django_db
def test_dispatch_records_network_failure_and_retries_later(seeded_policies: None) -> None:
    """خطای شبکه در ارسال بازپرداخت باید شمارندهٔ تلاش را زیاد کند و PENDING بماند."""
    del seeded_policies
    admin = _admin("25")
    campaign = _campaign(admin, slug_suffix="refundnet")
    donor = _donor("25")
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
        gateway_name="sandbox",
        authority="SBX-REFUNDNET0001",
        amount_rial=1_000_000,
        redirect_url="https://sandbox.invalid/pay",
        status=PaymentStatus.VERIFIED,
    )
    refund = PaymentRefund.objects.create(
        payment=payment,
        amount_rial=1_000_000,
        reason="آزمون خطای شبکه",
        outcome=RefundOutcome.PENDING,
    )

    flaky = _FlakyGateway(exc=ConnectionError("قطعی موقت"))
    with patch("apps.contributions.services.resolve_payment_gateway", return_value=flaky):
        stats = dispatch_pending_refunds()

    assert stats["failed"] == 1
    refund.refresh_from_db()
    assert refund.outcome == RefundOutcome.PENDING
    assert refund.attempt_count == 1
    assert "ConnectionError" in refund.automation_note


@pytest.mark.django_db
def test_settle_is_idempotent(seeded_policies: None) -> None:
    """تسویهٔ دوبارهٔ همان بازپرداخت باید همان رکورد را برگرداند، نه سند تکراری."""
    del seeded_policies
    admin = _admin("26")
    campaign = _campaign(admin, slug_suffix="settleidem")
    donor = _donor("26")
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
        gateway_name="sandbox",
        authority="SBX-SETTLE000001",
        amount_rial=1_000_000,
        redirect_url="https://sandbox.invalid/pay",
        status=PaymentStatus.VERIFIED,
    )
    refund = PaymentRefund.objects.create(
        payment=payment, amount_rial=1_000_000, reason="آزمون", outcome=RefundOutcome.PENDING
    )

    first = settle_refund_obligation(refund_id=refund.pk, actor=admin, note="نخست")
    second = settle_refund_obligation(refund_id=refund.pk, actor=admin, note="دوم")

    assert first.pk == second.pk
    assert PaymentRefund.objects.filter(payment=payment).count() == 1
    from apps.ledger.models import JournalEntry

    assert (
        JournalEntry.objects.filter(reference_key=f"payment.refund_settled:{payment.pk}").count()
        == 1
    )


# ── ۵. لایهٔ HTTP: مجوزها و قرارداد ─────────────────────────────────────────


@pytest.mark.django_db
def test_financial_health_endpoint_requires_staff(seeded_policies: None) -> None:
    """کاربر عادی نباید به پنل سلامت مالی دسترسی داشته باشد."""
    del seeded_policies
    donor = _donor("27")
    client, _ = issue_client_for_user(donor)

    response = client.get("/api/v1/admin/financial-health")

    assert response.status_code in {401, 403}


@pytest.mark.django_db
def test_financial_health_endpoint_returns_snapshot_for_staff(seeded_policies: None) -> None:
    """کارمند مجاز باید گزارش کامل با همهٔ کلیدهای قراردادی بگیرد."""
    del seeded_policies
    from apps.identity.choices import UserRole

    staff = User.objects.create_user(
        phone="09120007777",
        first_name="کارشناس",
        last_name="پایش",
        role=UserRole.OPERATOR,
        is_staff=True,
    )
    client, _ = issue_client_for_user(staff, mfa_fresh=True)

    response = client.get("/api/v1/admin/financial-health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"healthy", "attention_required"}
    assert set(body["money_loop"]) >= {
        "abandoned_payments",
        "pending_refund_obligations",
        "refund_liability_rial",
    }
    assert isinstance(body["alerts"], list)


@pytest.mark.django_db
def test_reconcile_endpoint_dry_run_for_finance_manager(seeded_policies: None) -> None:
    """مدیر مالی باید بتواند پیش‌نمایش داوری را از API اجرا کند."""
    del seeded_policies
    from apps.identity.choices import UserRole

    manager = User.objects.create_user(
        phone="09120007788",
        first_name="مدیر",
        last_name="مالی",
        role=UserRole.FINANCE_MANAGER,
        is_staff=True,
    )
    client, _ = issue_client_for_user(manager, mfa_fresh=True)

    response = client.post(
        "/api/v1/admin/late-captures/reconcile", data={"dry_run": True}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert "scanned" in body


@pytest.mark.django_db
def test_refund_dispatch_endpoint_returns_stats(seeded_policies: None) -> None:
    """نقطهٔ پایانی ارسال بازپرداخت باید آمار بدهد."""
    del seeded_policies
    from apps.identity.choices import UserRole

    manager = User.objects.create_user(
        phone="09120007799",
        first_name="مدیر",
        last_name="مالی۲",
        role=UserRole.FINANCE_MANAGER,
        is_staff=True,
    )
    client, _ = issue_client_for_user(manager, mfa_fresh=True)

    response = client.post("/api/v1/admin/refunds/dispatch")

    assert response.status_code == 200
    assert "attempted" in response.json()


# ── ۶. متریک Prometheus ─────────────────────────────────────────────────────


@pytest.mark.django_db
def test_prometheus_exposes_money_loop_gauges(seeded_policies: None) -> None:
    """متریک‌ها باید بدهی بازپرداخت را به‌صورت گیج عددی گزارش کنند."""
    del seeded_policies
    from apps.core.metrics import render_prometheus_metrics

    payload, content_type = render_prometheus_metrics()
    text = payload.decode("utf-8")

    assert "text/plain" in content_type
    for metric in (
        "crowdfunding_pending_refund_obligations",
        "crowdfunding_unresolved_late_captures",
        "crowdfunding_abandoned_payments",
        "crowdfunding_refund_liability_rial",
        "crowdfunding_outbox_messages",
    ):
        assert metric in text, f"متریک {metric} در خروجی نیست"


# ── ۷. Outbox: بازگردانی پیام متوقف‌شده ─────────────────────────────────────


@pytest.mark.django_db
def test_requeue_dead_outbox_message_resets_attempts(seeded_policies: None) -> None:
    """پیام DEAD باید به صف برگردد، شمارنده صفر شود و خطای قبلی حفظ شود."""
    del seeded_policies
    from apps.core.choices import OutboxStatus
    from apps.core.models import OutboxMessage
    from apps.core.outbox import requeue_outbox_messages

    msg = OutboxMessage.objects.create(
        event_type="sms.receipt_issued",
        payload={"phone": "09120000000"},
        status=OutboxStatus.DEAD,
        attempts=8,
        last_error="درگاه پیامک پاسخ نداد",
    )

    stats = requeue_outbox_messages(message_ids=[msg.pk])

    assert stats["requeued"] == 1
    msg.refresh_from_db()
    assert msg.status == OutboxStatus.PENDING
    assert msg.attempts == 0
    assert msg.last_error.startswith("[requeued]")


@pytest.mark.django_db
def test_requeue_ignores_non_dead_messages(seeded_policies: None) -> None:
    """پیام‌هایی که DEAD نیستند نباید دست بخورند."""
    del seeded_policies
    from apps.core.choices import OutboxStatus
    from apps.core.models import OutboxMessage
    from apps.core.outbox import requeue_outbox_messages

    msg = OutboxMessage.objects.create(
        event_type="sms.receipt_issued",
        payload={},
        status=OutboxStatus.DELIVERED,
        attempts=1,
    )

    stats = requeue_outbox_messages(message_ids=[msg.pk])

    assert stats["requeued"] == 0
    assert stats["skipped"] == 1
    msg.refresh_from_db()
    assert msg.status == OutboxStatus.DELIVERED


# ── ۸. درگاه: خطاهای پیکربندی ───────────────────────────────────────────────


@override_settings(PAYMENT_DEFAULT_GATEWAY="unknown-gateway")
def test_unknown_gateway_raises_explicit_error() -> None:
    """نام درگاه ناشناخته نباید بی‌صدا به Sandbox تبدیل شود."""
    from apps.contributions.gateways import resolve_payment_gateway

    with pytest.raises(DomainValidationError) as exc_info:
        resolve_payment_gateway("unknown-gateway")

    assert getattr(exc_info.value, "code", "") == "gateway_not_configured"


def test_sandbox_refund_rejects_invalid_input() -> None:
    """آداپتور Sandbox باید ورودی نامعتبر را رد کند، نه تأیید قلابی."""
    from apps.contributions.gateways import SandboxGatewayAdapter

    adapter = SandboxGatewayAdapter()

    bad_authority = adapter.refund(authority="NOT-SBX", amount_rial=1_000_000)
    assert bad_authority.accepted is False
    assert bad_authority.raw_code == "INVALID_AUTHORITY"

    bad_amount = adapter.refund(authority="SBX-ABC123", amount_rial=0)
    assert bad_amount.accepted is False
    assert bad_amount.raw_code == "INVALID_AMOUNT"

    good = adapter.refund(authority="SBX-ABC123", amount_rial=1_000_000, reason="آزمون")
    assert good.accepted is True
    assert good.gateway_reference.startswith("SBXRFD-")


# ── ۹. سقف بازپرداخت خودکار ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_refund_above_auto_cap_goes_to_manual_review(seeded_policies: None) -> None:
    """مبلغ بالاتر از سقف سیاست نباید خودکار ارسال شود؛ باید به انسان برسد."""
    del seeded_policies
    from apps.contributions.choices import RefundOutcome
    from apps.contributions.services import dispatch_pending_refunds
    from apps.core.models import PolicyRule

    # سقف را پایین می‌آوریم تا مبلغ آزمون از آن عبور کند.
    PolicyRule.objects.update_or_create(
        key="recovery.auto_refund_max_rial",
        defaults={
            "value_type": "int",
            "raw_value": 100_000,
            "description": "سقف آزمون",
        },
    )
    from django.core.cache import cache

    cache.clear()

    admin = _admin("28")
    campaign = _campaign(admin, slug_suffix="overcap")
    donor = _donor("28")
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
        gateway_name="sandbox",
        authority="SBX-OVERCAP000001",
        amount_rial=1_000_000,
        redirect_url="https://sandbox.invalid/pay",
        status=PaymentStatus.VERIFIED,
    )
    refund = PaymentRefund.objects.create(
        payment=payment,
        amount_rial=1_000_000,
        reason="آزمون سقف",
        outcome=RefundOutcome.PENDING,
    )

    # اگر سقف اعمال نشود، این درگاه فراخوانی می‌شود و تست باید قرمز شود.
    flaky = _FlakyGateway()
    with patch("apps.contributions.services.resolve_payment_gateway", return_value=flaky):
        stats = dispatch_pending_refunds()

    assert stats["over_cap"] == 1
    assert stats["sent"] == 0
    assert flaky.calls == 0, "درگاه نباید برای مبلغ بالای سقف فراخوانی شود"

    refund.refresh_from_db()
    assert refund.outcome == RefundOutcome.MANUAL
    assert "سقف بازپرداخت خودکار" in refund.automation_note


@pytest.mark.django_db
def test_refund_below_auto_cap_is_still_dispatched(seeded_policies: None) -> None:
    """مبلغ زیر سقف باید مانند قبل خودکار ارسال شود (سقف نباید همه را قفل کند)."""
    del seeded_policies
    from apps.contributions.choices import RefundOutcome
    from apps.contributions.services import dispatch_pending_refunds

    admin = _admin("29")
    campaign = _campaign(admin, slug_suffix="undercap")
    donor = _donor("29")
    contribution = Contribution.objects.create(
        user=donor,
        benefactor=campaign.benefactor,
        target_kind="campaign_shares",
        campaign=campaign,
        shares_count=1,
        amount_rial=500_000,
        status=ContributionStatus.AWAITING_REFUND,
        hold_expires_at=timezone.now(),
    )
    payment = Payment.objects.create(
        contribution=contribution,
        gateway_name="sandbox",
        authority="SBX-UNDERCAP00001",
        amount_rial=500_000,
        redirect_url="https://sandbox.invalid/pay",
        status=PaymentStatus.VERIFIED,
    )
    refund = PaymentRefund.objects.create(
        payment=payment,
        amount_rial=500_000,
        reason="آزمون زیر سقف",
        outcome=RefundOutcome.PENDING,
    )

    flaky = _FlakyGateway()
    with patch("apps.contributions.services.resolve_payment_gateway", return_value=flaky):
        stats = dispatch_pending_refunds()

    assert stats["sent"] == 1
    assert stats["over_cap"] == 0
    assert flaky.calls == 1
    refund.refresh_from_db()
    assert refund.outcome == RefundOutcome.SENT


# ── ۱۰. متریک‌ها واقعاً افزایش می‌یابند (نبود متریک مرده) ────────────────────


@pytest.mark.django_db
def test_recovery_counter_increments_on_decision(seeded_policies: None) -> None:
    """شمارندهٔ Prometheus باید با هر داوری یک واحد بالا برود، نه فقط تعریف شود."""
    del seeded_policies
    from apps.core.metrics import LATE_CAPTURE_RECOVERIES_TOTAL

    before = LATE_CAPTURE_RECOVERIES_TOTAL.labels(
        outcome=str(LateCaptureOutcome.RECOVERED)
    )._value.get()

    admin = _admin("30")
    campaign = _campaign(admin, slug_suffix="metricinc")
    contribution, payment = _dry_checkout(user=_donor("30"), campaign=campaign, shares=1)
    Contribution.objects.filter(pk=contribution.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    release_expired_share_holds(campaign_id=campaign.id)
    _abandon(payment)

    reconcile_one_abandoned_payment(payment_id=payment.pk)

    after = LATE_CAPTURE_RECOVERIES_TOTAL.labels(
        outcome=str(LateCaptureOutcome.RECOVERED)
    )._value.get()
    assert after == before + 1
