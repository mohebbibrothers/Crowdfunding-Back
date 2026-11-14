"""تست‌های موتور تعهد کمک مستمر — ریاضی تقویم، idempotency، یادآوری و تسویه.

فلسفهٔ این فایل: **پول و زمان** دو چیزند که اشتباه در آن‌ها گران است. پس
تقریباً هر تست اینجا به یکی از این دو حمله می‌کند:

  • «آیا ممکن است دو بار پول کسر شود؟»
  • «آیا ممکن است یک قسط بی‌دلیل ساخته یا جا افتاده شود؟»
  • «آیا ممکن است خیر بی‌خبر از توقف کمکش بماند؟»
"""

from __future__ import annotations

from datetime import date, timedelta
import json
from typing import Any

from django.utils import timezone
import pytest

from apps.contributions.choices import (
    ContributionStatus,
    ContributionTargetKind,
    InstallmentStatus,
    PledgeCancelReason,
    PledgeFrequency,
    PledgeStatus,
)
from apps.contributions.models import (
    Contribution,
    PledgeInstallment,
    RecurringPledge,
)
from apps.contributions.recurring import (
    build_pledge_stats,
    cancel_pledge,
    create_recurring_pledge,
    dispatch_pledge_reminders,
    expire_stale_installments,
    materialize_due_installments,
    pause_pledge,
    pay_installment,
    pledge_summary_for_user,
    resume_paused_pledges,
    resume_pledge,
    settle_installment_payment,
    skip_installment,
    update_pledge,
)
from apps.contributions.scheduling import (
    add_months,
    advance_due_date,
    is_within_reminder_window,
    months_between,
    next_occurrence,
    tehran_today,
)
from apps.core.errors import ConflictError, NotFoundError, ValidationError as DomainValidationError
from apps.core.models import OutboxMessage
from tests.test_capture_recovery import _admin, _campaign, _donor

# ══════════════════════════════════════════════════════════════════════════════
# ۱) ریاضی تقویم — بنیادی‌ترین لایه، بدون دیتابیس
# ══════════════════════════════════════════════════════════════════════════════


def test_next_occurrence_can_land_today_when_anchor_matches() -> None:
    """اگر امروز روز میخ باشد، قسط باید امروز باشد نه ماه بعد.

    این تست از یک باگ واقعی محافظت می‌کند: نسخهٔ اول حلقه از ``interval_months``
    شروع می‌شد و ماه جاری را کامل می‌پراند — خیر یک ماه کمک را از دست می‌داد.
    """
    assert next_occurrence(anchor_day=21, after=date(2026, 4, 20), interval_months=1) == date(
        2026, 4, 21
    )


def test_next_occurrence_is_strictly_after_reference() -> None:
    """``after`` اکیداً است — وگرنه همان قسط دو بار ساخته می‌شود."""
    assert next_occurrence(anchor_day=21, after=date(2026, 4, 21), interval_months=1) == date(
        2026, 5, 21
    )


def test_anchor_day_is_restored_after_short_month() -> None:
    """میخ روز ۳۱ در اسفند به ۲۸ می‌افتد، ولی فروردین دوباره ۳۱ می‌شود.

    «همیشه به آخرین روز برو» یک انتخاب ساده‌لوحانه است که خیر را برای همیشه
    از روز دلخواهش دور می‌کند.
    """
    feb = next_occurrence(anchor_day=31, after=date(2026, 1, 31), interval_months=1)
    assert feb == date(2026, 2, 28)
    assert next_occurrence(anchor_day=31, after=feb, interval_months=1) == date(2026, 3, 31)


def test_quarterly_interval_skips_two_months() -> None:
    """تعهد سه‌ماهه دقیقاً سه ماه جلو می‌رود، نه یک ماه."""
    assert next_occurrence(anchor_day=15, after=date(2026, 1, 16), interval_months=3) == date(
        2026, 4, 15
    )


def test_advance_due_date_never_moves_backwards() -> None:
    """حتی اگر ساعت سیستم عقب باشد، سررسید بعدی همیشه جلوست."""
    result = advance_due_date(
        current_due=date(2026, 1, 10),
        anchor_day=10,
        interval_months=1,
        from_date=date(2026, 6, 1),
    )
    assert result > date(2026, 6, 1)


def test_add_months_preserves_anchor_across_year_boundary() -> None:
    """افزودن ماه از مرز سال عبور می‌کند بدون گم‌کردن میخ روز."""
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_reminder_window_is_half_open() -> None:
    """پنجرهٔ ۹ تا ۲۱: ساعت ۹ مجاز، ساعت ۲۱ ممنوع، ۳ بامداد ممنوع."""
    assert is_within_reminder_window(hour=9, start_hour=9, end_hour=21) is True
    assert is_within_reminder_window(hour=20, start_hour=9, end_hour=21) is True
    assert is_within_reminder_window(hour=21, start_hour=9, end_hour=21) is False
    assert is_within_reminder_window(hour=3, start_hour=9, end_hour=21) is False


def test_invalid_anchor_day_is_rejected_loudly() -> None:
    """میخ روز ۰ یا ۳۲ یعنی باگ فراخوان — نه تاریخ بی‌معنا."""
    with pytest.raises(ValueError):
        next_occurrence(anchor_day=0, after=date(2026, 1, 1), interval_months=1)
    with pytest.raises(ValueError):
        next_occurrence(anchor_day=32, after=date(2026, 1, 1), interval_months=1)


def test_months_between_handles_reverse_order() -> None:
    """ترتیب معکوس باید صفر بدهد، نه عدد منفی که آمار را خراب می‌کند."""
    assert months_between(date(2026, 6, 1), date(2026, 1, 1)) == 0
    assert months_between(date(2026, 1, 1), date(2026, 6, 1)) == 5


# ══════════════════════════════════════════════════════════════════════════════
# ۲) ساخت تعهد — قواعدی که ماه‌ها تکرار می‌شوند
# ══════════════════════════════════════════════════════════════════════════════


def _pledge(
    *,
    admin: Any,
    donor: Any,
    campaign: Any,
    amount: int = 1_000_000,
    frequency: str = PledgeFrequency.MONTHLY,
) -> Any:
    return create_recurring_pledge(
        user=donor,
        benefactor=campaign.benefactor,
        target_kind=ContributionTargetKind.CAMPAIGN_SHARES,
        amount_rial=amount,
        frequency=frequency,
        campaign=campaign,
    )


@pytest.mark.django_db
def test_pledge_creation_builds_first_installment(seeded_policies: None) -> None:
    """تعهد بدون قسط اول بی‌معناست — خیر باید بداند اولین پرداخت کِی است."""
    del seeded_policies
    admin = _admin("50")
    donor = _donor("50")
    campaign = _campaign(admin, slug_suffix="p50")

    result = _pledge(admin=admin, donor=donor, campaign=campaign)

    assert result.pledge.status == PledgeStatus.ACTIVE
    assert result.first_installment.sequence == 1
    assert result.first_installment.amount_rial == 1_000_000
    assert result.first_installment.status == InstallmentStatus.SCHEDULED
    assert result.first_installment.idempotency_key == f"pledge:{result.pledge.pk}:seq:1"


@pytest.mark.django_db
def test_amount_below_policy_floor_is_rejected(seeded_policies: None) -> None:
    """قسط ۱۰ هزار ریالی، هزینهٔ پیامکش بیشتر از خودش است."""
    del seeded_policies
    admin = _admin("51")
    donor = _donor("51")
    campaign = _campaign(admin, slug_suffix="p51")

    with pytest.raises(DomainValidationError) as exc:
        _pledge(admin=admin, donor=donor, campaign=campaign, amount=10_000)
    assert getattr(exc.value, "code", "") == "pledge_amount_too_low"


@pytest.mark.django_db
def test_missing_target_is_rejected(seeded_policies: None) -> None:
    """تعهد سهم‌محور بدون حرکت یعنی قسطی که به جایی نمی‌رسد."""
    del seeded_policies
    admin = _admin("52")
    donor = _donor("52")

    with pytest.raises(DomainValidationError) as exc:
        create_recurring_pledge(
            user=donor,
            benefactor=admin,
            target_kind=ContributionTargetKind.CAMPAIGN_SHARES,
            amount_rial=1_000_000,
        )
    assert getattr(exc.value, "code", "") == "pledge_invalid_target"


@pytest.mark.django_db
def test_active_pledge_cap_is_enforced(seeded_policies: None) -> None:
    """سقف تعهد فعال از فشار مالی و اسپم جلوگیری می‌کند."""
    del seeded_policies
    admin = _admin("53")
    donor = _donor("53")
    campaign = _campaign(admin, slug_suffix="p53")

    for _ in range(5):
        _pledge(admin=admin, donor=donor, campaign=campaign)

    with pytest.raises(ConflictError) as exc:
        _pledge(admin=admin, donor=donor, campaign=campaign)
    assert getattr(exc.value, "code", "") == "pledge_limit_reached"


@pytest.mark.django_db
def test_disabled_engine_blocks_creation(seeded_policies: None) -> None:
    """کلید خاموش باید واقعاً خاموش کند — نه فقط در مستندات."""
    del seeded_policies
    from apps.core.policy import set_policy_value

    admin = _admin("54")
    donor = _donor("54")
    campaign = _campaign(admin, slug_suffix="p54")
    set_policy_value(
        key="pledge.engine_enabled",
        value=False,
        actor_id=admin.pk,
        reason="توقف اضطراری موتور تعهد",
    )

    with pytest.raises(ConflictError) as exc:
        _pledge(admin=admin, donor=donor, campaign=campaign)
    assert getattr(exc.value, "code", "") == "pledge_engine_disabled"


# ══════════════════════════════════════════════════════════════════════════════
# ۳) چرخهٔ تولید قسط — جایی که double-charge متولد می‌شود اگر بی‌دقت باشیم
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_materialize_creates_installment_and_advances_due_date(seeded_policies: None) -> None:
    """هر اجرا یک قسط می‌سازد و سررسید را جلو می‌برد — نه بیشتر، نه کمتر."""
    del seeded_policies
    admin = _admin("55")
    donor = _donor("55")
    campaign = _campaign(admin, slug_suffix="p55")
    result = _pledge(admin=admin, donor=donor, campaign=campaign)
    pledge = result.pledge
    due = pledge.next_due_date

    stats = materialize_due_installments(as_of=due)

    assert stats.installments_created == 1
    assert stats.pledges_advanced == 1
    pledge.refresh_from_db()
    assert pledge.next_due_date > due
    assert PledgeInstallment.objects.filter(pledge=pledge).count() == 2


@pytest.mark.django_db
def test_running_cycle_twice_does_not_double_charge(seeded_policies: None) -> None:
    """**مهم‌ترین تست این فایل.**

    دو اجرای متوالی کرون نباید دو قسط بسازند. یکتایی ``(pledge, sequence)``
    تنها محافظ واقعی است؛ اگر این تست بشکند، خیرها دو بار پول می‌دهند.
    """
    del seeded_policies
    admin = _admin("56")
    donor = _donor("56")
    campaign = _campaign(admin, slug_suffix="p56")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge
    due = pledge.next_due_date

    materialize_due_installments(as_of=due)
    second = materialize_due_installments(as_of=due)

    assert second.installments_created == 0
    assert PledgeInstallment.objects.filter(pledge=pledge, sequence=2).count() == 1


@pytest.mark.django_db
def test_inactive_pledge_is_skipped_by_cycle(seeded_policies: None) -> None:
    """تعهد متوقف نباید قسط تولید کند — این همان تعریف «توقف» است."""
    del seeded_policies
    admin = _admin("57")
    donor = _donor("57")
    campaign = _campaign(admin, slug_suffix="p57")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge
    pause_pledge(pledge_id=pledge.pk, user=donor)

    stats = materialize_due_installments(as_of=pledge.next_due_date + timedelta(days=5))

    assert stats.installments_created == 0


# ══════════════════════════════════════════════════════════════════════════════
# ۴) یادآوری — محترمانه، محدود، و بدون تکرار
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_reminder_is_not_sent_outside_window(seeded_policies: None) -> None:
    """ساعت ۳ بامداد هیچ پیامکی نمی‌رود، حتی اگر قسط سررسید شده باشد."""
    del seeded_policies
    admin = _admin("58")
    donor = _donor("58")
    campaign = _campaign(admin, slug_suffix="p58")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge
    materialize_due_installments(as_of=pledge.next_due_date)

    night = timezone.localtime(tehran_now_factory()).replace(hour=3, minute=0)
    stats = dispatch_pledge_reminders(now=night)

    assert stats.window_open is False
    assert stats.sent == 0


@pytest.mark.django_db
def test_reminder_is_deduplicated_by_outbox_key(seeded_policies: None) -> None:
    """اجرای دوبارهٔ کرون در همان دقیقه، پیامک دوم نمی‌سازد."""
    del seeded_policies
    admin = _admin("59")
    donor = _donor("59")
    campaign = _campaign(admin, slug_suffix="p59")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge
    materialize_due_installments(as_of=pledge.next_due_date)

    noon = timezone.localtime(tehran_now_factory()).replace(hour=12, minute=0)
    first = dispatch_pledge_reminders(now=noon)
    second = dispatch_pledge_reminders(now=noon)

    assert first.sent >= 1
    assert second.sent == 0


@pytest.mark.django_db
def test_reminder_cap_silences_after_max(seeded_policies: None) -> None:
    """پس از سقف یادآوری، سکوت. تکرار بی‌پایان = مزاحمت."""
    del seeded_policies
    admin = _admin("60")
    donor = _donor("60")
    campaign = _campaign(admin, slug_suffix="p60")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge
    materialize_due_installments(as_of=pledge.next_due_date)

    installment = PledgeInstallment.objects.filter(pledge=pledge, sequence=2).first()
    assert installment is not None
    installment.reminder_count = 2
    installment.status = InstallmentStatus.REMINDED
    installment.save(update_fields=["reminder_count", "status", "updated_at"])

    noon = timezone.localtime(tehran_now_factory()).replace(hour=12, minute=0)
    dispatch_pledge_reminders(now=noon)

    installment.refresh_from_db()
    assert installment.reminder_count == 2


# ══════════════════════════════════════════════════════════════════════════════
# ۵) انقضا — توقف بی‌صدا ممنوع
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_past_grace_marks_installment_failed(seeded_policies: None) -> None:
    """قسطی که مهلتش گذشته باید «شکست‌خورده» شود، نه اینکه باز بماند."""
    del seeded_policies
    admin = _admin("61")
    donor = _donor("61")
    campaign = _campaign(admin, slug_suffix="p61")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge

    stats = expire_stale_installments(as_of=pledge.next_due_date + timedelta(days=30))

    assert stats.expired_installments == 1
    assert (
        PledgeInstallment.objects.filter(pledge=pledge, status=InstallmentStatus.FAILED).count()
        == 1
    )


@pytest.mark.django_db
def test_three_failures_expire_pledge_and_notify_donor(seeded_policies: None) -> None:
    """خیری که فکر می‌کند ماهانه می‌دهد ولی نمی‌دهد، باید خبردار شود."""
    del seeded_policies
    admin = _admin("62")
    donor = _donor("62")
    campaign = _campaign(admin, slug_suffix="p62")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge

    for _ in range(3):
        PledgeInstallment.objects.create(
            pledge=pledge,
            sequence=100 + _,
            due_date=date(2025, 1, 1) + timedelta(days=30 * _),
            grace_until=date(2025, 1, 8) + timedelta(days=30 * _),
            amount_rial=1_000_000,
            status=InstallmentStatus.SCHEDULED,
            idempotency_key=f"test:{pledge.pk}:100{_}",
        )

    stats = expire_stale_installments(as_of=date(2025, 6, 1))

    assert stats.expired_installments >= 3
    assert stats.pledges_expired == 1
    pledge.refresh_from_db()
    assert pledge.status == PledgeStatus.EXPIRED
    assert OutboxMessage.objects.filter(
        event_type="notification.pledge_expired", aggregate_id=str(pledge.pk)
    ).exists()


# ══════════════════════════════════════════════════════════════════════════════
# ۶) تسویه — پیوند پول به قسط
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_settlement_marks_paid_and_updates_totals(seeded_policies: None) -> None:
    """پرداخت موفق باید قسط را PAID کند و شمارنده‌های تعهد را بالا ببرد."""
    del seeded_policies
    admin = _admin("63")
    donor = _donor("63")
    campaign = _campaign(admin, slug_suffix="p63")
    result = _pledge(admin=admin, donor=donor, campaign=campaign)
    contribution = Contribution.objects.create(
        user=donor,
        benefactor=campaign.benefactor,
        target_kind=ContributionTargetKind.CAMPAIGN_SHARES,
        campaign=campaign,
        shares_count=1,
        amount_rial=1_000_000,
        status=ContributionStatus.PAID,
        hold_expires_at=timezone.now(),
    )

    installment = settle_installment_payment(
        installment_id=result.first_installment.pk, contribution=contribution
    )

    assert installment.status == InstallmentStatus.PAID
    pledge = RecurringPledge.objects.get(pk=result.pledge.pk)
    assert pledge.total_paid_rial == 1_000_000
    assert pledge.installments_paid == 1
    assert pledge.last_paid_at is not None


@pytest.mark.django_db
def test_settlement_is_idempotent(seeded_policies: None) -> None:
    """وب‌هوک تکراری درگاه نباید قسط را دو بار بشمارد."""
    del seeded_policies
    admin = _admin("64")
    donor = _donor("64")
    campaign = _campaign(admin, slug_suffix="p64")
    result = _pledge(admin=admin, donor=donor, campaign=campaign)
    contribution = Contribution.objects.create(
        user=donor,
        benefactor=campaign.benefactor,
        target_kind=ContributionTargetKind.CAMPAIGN_SHARES,
        campaign=campaign,
        shares_count=1,
        amount_rial=1_000_000,
        status=ContributionStatus.PAID,
        hold_expires_at=timezone.now(),
    )

    settle_installment_payment(
        installment_id=result.first_installment.pk, contribution=contribution
    )
    settle_installment_payment(
        installment_id=result.first_installment.pk, contribution=contribution
    )

    pledge = RecurringPledge.objects.get(pk=result.pledge.pk)
    assert pledge.total_paid_rial == 1_000_000  # نه ۲٬۰۰۰٬۰۰۰
    assert pledge.installments_paid == 1


@pytest.mark.django_db
def test_successful_payment_resets_failure_counter(seeded_policies: None) -> None:
    """یک پرداخت موفق، زنجیرهٔ شکست را می‌شکند — وگرنه تعهد بی‌دلیل منقضی می‌شود."""
    del seeded_policies
    admin = _admin("65")
    donor = _donor("65")
    campaign = _campaign(admin, slug_suffix="p65")
    result = _pledge(admin=admin, donor=donor, campaign=campaign)
    RecurringPledge.objects.filter(pk=result.pledge.pk).update(consecutive_failures=2)

    contribution = Contribution.objects.create(
        user=donor,
        benefactor=campaign.benefactor,
        target_kind=ContributionTargetKind.CAMPAIGN_SHARES,
        campaign=campaign,
        shares_count=1,
        amount_rial=1_000_000,
        status=ContributionStatus.PAID,
        hold_expires_at=timezone.now(),
    )
    settle_installment_payment(
        installment_id=result.first_installment.pk, contribution=contribution
    )

    pledge = RecurringPledge.objects.get(pk=result.pledge.pk)
    assert pledge.consecutive_failures == 0


# ══════════════════════════════════════════════════════════════════════════════
# ۷) کنترل خیر — توقف، بازگشت، لغو، رد قسط
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_pause_voids_open_installments_but_keeps_paid(seeded_policies: None) -> None:
    """توقف، اقساط باز را باطل می‌کند و اقساط پرداخت‌شده را دست نمی‌زند."""
    del seeded_policies
    admin = _admin("66")
    donor = _donor("66")
    campaign = _campaign(admin, slug_suffix="p66")
    result = _pledge(admin=admin, donor=donor, campaign=campaign)
    paid = PledgeInstallment.objects.create(
        pledge=result.pledge,
        sequence=99,
        due_date=date(2025, 1, 1),
        grace_until=date(2025, 1, 8),
        amount_rial=1_000_000,
        status=InstallmentStatus.PAID,
        idempotency_key=f"test:{result.pledge.pk}:99",
    )

    pause_pledge(pledge_id=result.pledge.pk, user=donor)

    result.first_installment.refresh_from_db()
    paid.refresh_from_db()
    assert result.first_installment.status == InstallmentStatus.VOIDED
    assert paid.status == InstallmentStatus.PAID


@pytest.mark.django_db
def test_paused_pledge_resumes_automatically_when_until_passes(seeded_policies: None) -> None:
    """خیری که «یک ماه توقف» زده نباید خودش یادش بیفتد که دوباره فعال کند."""
    del seeded_policies
    admin = _admin("67")
    donor = _donor("67")
    campaign = _campaign(admin, slug_suffix="p67")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge
    pause_pledge(pledge_id=pledge.pk, user=donor, until=tehran_today() - timedelta(days=1))

    resumed = resume_paused_pledges()

    assert resumed == 1
    pledge.refresh_from_db()
    assert pledge.status == PledgeStatus.ACTIVE
    assert pledge.pause_until is None


@pytest.mark.django_db
def test_cancel_voids_open_and_is_terminal(seeded_policies: None) -> None:
    """لغو دائمی است؛ اجرای دوباره نباید تاریخ لغو اول را بازنویسی کند."""
    del seeded_policies
    admin = _admin("68")
    donor = _donor("68")
    campaign = _campaign(admin, slug_suffix="p68")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge

    first = cancel_pledge(pledge_id=pledge.pk, user=donor, reason=PledgeCancelReason.TOO_EXPENSIVE)
    original_cancelled_at = first.cancelled_at
    second = cancel_pledge(pledge_id=pledge.pk, user=donor)

    assert second.status == PledgeStatus.CANCELLED
    assert second.cancel_reason == PledgeCancelReason.TOO_EXPENSIVE
    assert second.cancelled_at == original_cancelled_at


@pytest.mark.django_db
def test_skip_keeps_pledge_alive_and_clears_failures(seeded_policies: None) -> None:
    """رد آگاهانه «شکست» نیست: تعهد زنده می‌ماند و شمارندهٔ شکست صفر می‌شود."""
    del seeded_policies
    admin = _admin("69")
    donor = _donor("69")
    campaign = _campaign(admin, slug_suffix="p69")
    result = _pledge(admin=admin, donor=donor, campaign=campaign)
    RecurringPledge.objects.filter(pk=result.pledge.pk).update(consecutive_failures=2)

    skip_installment(installment_id=result.first_installment.pk, user=donor)

    pledge = RecurringPledge.objects.get(pk=result.pledge.pk)
    assert pledge.status == PledgeStatus.ACTIVE
    assert pledge.consecutive_failures == 0
    assert pledge.installments_skipped == 1


@pytest.mark.django_db
def test_other_users_pledge_is_invisible_not_forbidden(seeded_policies: None) -> None:
    """۴۰۴ برای تعهد دیگران — نه ۴۰۳، چون ۴۰۳ وجود شناسه را تأیید می‌کند."""
    del seeded_policies
    admin = _admin("70")
    donor = _donor("70")
    stranger = _donor("71")
    campaign = _campaign(admin, slug_suffix="p70")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge

    with pytest.raises(NotFoundError):
        pause_pledge(pledge_id=pledge.pk, user=stranger)
    with pytest.raises(NotFoundError):
        cancel_pledge(pledge_id=pledge.pk, user=stranger)


@pytest.mark.django_db
def test_update_amount_does_not_move_due_date(seeded_policies: None) -> None:
    """کم‌کردن مبلغ نباید سررسید را عقب بیندازد — این تنبیه ناخواسته است."""
    del seeded_policies
    admin = _admin("72")
    donor = _donor("72")
    campaign = _campaign(admin, slug_suffix="p72")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge
    original_due = pledge.next_due_date

    update_pledge(pledge_id=pledge.pk, user=donor, amount_rial=2_000_000)

    pledge.refresh_from_db()
    assert pledge.amount_rial == 2_000_000
    assert pledge.next_due_date == original_due


# ══════════════════════════════════════════════════════════════════════════════
# ۸) پرداخت — پورت و مسدودسازی‌ها
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_paid_installment_cannot_be_paid_again(seeded_policies: None) -> None:
    """پرداخت دوبارهٔ قسط پرداخت‌شده یعنی کسر دوم — باید رد شود."""
    del seeded_policies
    admin = _admin("73")
    donor = _donor("73")
    campaign = _campaign(admin, slug_suffix="p73")
    result = _pledge(admin=admin, donor=donor, campaign=campaign)
    PledgeInstallment.objects.filter(pk=result.first_installment.pk).update(
        status=InstallmentStatus.PAID
    )

    with pytest.raises(ConflictError) as exc:
        pay_installment(installment_id=result.first_installment.pk, user=donor)
    assert getattr(exc.value, "code", "") == "installment_already_paid"


@pytest.mark.django_db
def test_voided_installment_cannot_be_paid(seeded_policies: None) -> None:
    """قسط باطل‌شده (تعهد لغو/متوقف) نباید قابل پرداخت باشد."""
    del seeded_policies
    admin = _admin("74")
    donor = _donor("74")
    campaign = _campaign(admin, slug_suffix="p74")
    result = _pledge(admin=admin, donor=donor, campaign=campaign)
    pause_pledge(pledge_id=result.pledge.pk, user=donor)

    with pytest.raises(ConflictError) as exc:
        pay_installment(installment_id=result.first_installment.pk, user=donor)
    assert getattr(exc.value, "code", "") in {"installment_not_payable", "installment_already_paid"}


# ══════════════════════════════════════════════════════════════════════════════
# ۹) آمار — عددی که بودجه‌بندی را ممکن می‌کند
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_mrr_normalizes_quarterly_to_monthly(seeded_policies: None) -> None:
    """تعهد سه‌ماههٔ ۳۰۰ هزار = ۱۰۰ هزار در ماه. MRR باید همین را بگوید."""
    del seeded_policies
    admin = _admin("75")
    donor = _donor("75")
    campaign = _campaign(admin, slug_suffix="p75")

    create_recurring_pledge(
        user=donor,
        benefactor=campaign.benefactor,
        target_kind=ContributionTargetKind.CAMPAIGN_SHARES,
        amount_rial=3_000_000,
        frequency=PledgeFrequency.QUARTERLY,
        campaign=campaign,
    )

    stats = build_pledge_stats()
    assert stats["monthly_recurring_revenue_rial"] == 1_000_000
    assert stats["active_pledges"] == 1


@pytest.mark.django_db
def test_collection_rate_is_one_when_nothing_settled(seeded_policies: None) -> None:
    """سیستم خالی نرخ وصول ۰٪ ندارد — ۰٪ یعنی «همه بدحساب‌اند» که دروغ است."""
    del seeded_policies
    stats = build_pledge_stats()
    assert stats["collection_rate"] == 1.0


@pytest.mark.django_db
def test_pledge_summary_counts_only_own_pledges(seeded_policies: None) -> None:
    """داشبورد خیر نباید تعهد دیگران را بشمارد."""
    del seeded_policies
    admin = _admin("76")
    donor = _donor("76")
    other = _donor("77")
    campaign = _campaign(admin, slug_suffix="p76")

    _pledge(admin=admin, donor=donor, campaign=campaign)
    _pledge(admin=admin, donor=other, campaign=campaign)

    summary = pledge_summary_for_user(user=donor)
    assert summary["active_count"] == 1
    assert summary["monthly_commitment_rial"] == 1_000_000


def tehran_now_factory() -> Any:
    """زمان فعلی aware — برای ساختن ساعت‌های مشخص در تست‌های پنجرهٔ یادآوری."""
    from apps.contributions.scheduling import tehran_now

    return tehran_now()


# ══════════════════════════════════════════════════════════════════════════════
# ۱۰) سطح API — قرارداد با تیم فرانت‌اند
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_api_creates_pledge_and_returns_toman(seeded_policies: None) -> None:
    """خروجی API باید هم ریال و هم تومان برگرداند — فرانت نباید تقسیم کند."""
    del seeded_policies
    from tests.conftest import issue_client_for_user

    admin = _admin("80")
    donor = _donor("80")
    campaign = _campaign(admin, slug_suffix="api80")
    client, _tokens = issue_client_for_user(donor)

    response = client.post(
        "/api/v1/me/pledges",
        {
            "target_kind": "campaign_shares",
            "campaign_id": str(campaign.pk),
            "amount_rial": 1_000_000,
            "frequency": "monthly",
        },
        format="json",
    )

    assert response.status_code == 201, response.content
    body = response.json()
    assert body["amount_rial"] == 1_000_000
    assert body["amount_toman"] == 100_000
    assert body["status"] == "active"
    assert body["next_payable_installment_id"] is not None
    assert body["open_installments"] == 1


@pytest.mark.django_db
def test_api_rejects_amount_under_floor_with_clear_code(seeded_policies: None) -> None:
    """خطای مبلغ باید صریح و قابل‌نمایش به کاربر باشد، نه ۵۰۰."""
    del seeded_policies
    from tests.conftest import issue_client_for_user

    admin = _admin("81")
    donor = _donor("81")
    campaign = _campaign(admin, slug_suffix="api81")
    client, _tokens = issue_client_for_user(donor)

    response = client.post(
        "/api/v1/me/pledges",
        {
            "target_kind": "campaign_shares",
            "campaign_id": str(campaign.pk),
            "amount_rial": 5_000,
        },
        format="json",
    )

    # ۴۲۲ = ValidationError دامنه (قرارداد موجود پروژه)؛ ۴۰۰ برای نقض فرمت است.
    assert response.status_code == 422
    assert "pledge_amount_too_low" in response.content.decode()


@pytest.mark.django_db
def test_api_hides_other_users_pledge_behind_404(seeded_policies: None) -> None:
    """شناسهٔ تعهد دیگران نباید حتی وجودش تأیید شود."""
    del seeded_policies
    from tests.conftest import issue_client_for_user

    admin = _admin("82")
    owner = _donor("82")
    stranger = _donor("83")
    campaign = _campaign(admin, slug_suffix="api82")
    pledge = _pledge(admin=admin, donor=owner, campaign=campaign).pledge
    client, _tokens = issue_client_for_user(stranger)

    response = client.get(f"/api/v1/me/pledges/{pledge.pk}")

    assert response.status_code == 404


@pytest.mark.django_db
def test_api_skip_installment_keeps_pledge_active(seeded_policies: None) -> None:
    """«این ماه نمی‌پردازم» نباید کل تعهد را از بین ببرد."""
    del seeded_policies
    from tests.conftest import issue_client_for_user

    admin = _admin("84")
    donor = _donor("84")
    campaign = _campaign(admin, slug_suffix="api84")
    result = _pledge(admin=admin, donor=donor, campaign=campaign)
    client, _tokens = issue_client_for_user(donor)

    response = client.post(
        f"/api/v1/me/pledges/{result.pledge.pk}/installments/{result.first_installment.pk}/skip",
        {"reason": "این ماه توان پرداخت ندارم"},
        format="json",
    )

    assert response.status_code == 200, response.content
    assert response.json()["status"] == "skipped"
    result.pledge.refresh_from_db()
    assert result.pledge.status == PledgeStatus.ACTIVE


@pytest.mark.django_db
def test_admin_stats_endpoint_exposes_mrr(seeded_policies: None) -> None:
    """مدیر خیریه باید MRR را ببیند — بدون آن بودجه‌بندی ممکن نیست."""
    del seeded_policies
    from tests.conftest import issue_client_for_user

    admin = _admin("85")
    donor = _donor("85")
    campaign = _campaign(admin, slug_suffix="api85")
    _pledge(admin=admin, donor=donor, campaign=campaign, amount=2_000_000)
    client, _tokens = issue_client_for_user(admin, mfa_fresh=True)

    response = client.get("/api/v1/admin/pledges/stats")

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["monthly_recurring_revenue_rial"] == 2_000_000
    assert body["monthly_recurring_revenue_toman"] == 200_000
    assert body["active_pledges"] == 1


@pytest.mark.django_db
def test_admin_list_masks_donor_phone(seeded_policies: None) -> None:
    """پنل مدیریت نباید شمارهٔ کامل خیر را نشان دهد."""
    del seeded_policies
    from tests.conftest import issue_client_for_user

    admin = _admin("86")
    donor = _donor("86")
    campaign = _campaign(admin, slug_suffix="api86")
    _pledge(admin=admin, donor=donor, campaign=campaign)
    client, _tokens = issue_client_for_user(admin, mfa_fresh=True)

    response = client.get("/api/v1/admin/pledges")

    assert response.status_code == 200, response.content
    rows = response.json()
    assert len(rows) == 1
    assert "*" in rows[0]["user_phone_masked"]
    assert donor.phone not in response.content.decode()


# ══════════════════════════════════════════════════════════════════════════════
# ۱۱) مسیرهای خطا و حالت‌های مرزی — جایی که باگ‌ها پنهان می‌شوند
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_invalid_frequency_is_rejected(seeded_policies: None) -> None:
    """تناوب ناشناخته باید صریح رد شود، نه اینکه ماهانه فرض شود."""
    del seeded_policies
    admin = _admin("90")
    donor = _donor("90")
    campaign = _campaign(admin, slug_suffix="e90")

    with pytest.raises(DomainValidationError) as exc:
        create_recurring_pledge(
            user=donor,
            benefactor=campaign.benefactor,
            target_kind=ContributionTargetKind.CAMPAIGN_SHARES,
            amount_rial=1_000_000,
            frequency="weekly",
            campaign=campaign,
        )
    assert getattr(exc.value, "code", "") == "pledge_invalid_frequency"


@pytest.mark.django_db
def test_invalid_start_day_is_rejected(seeded_policies: None) -> None:
    """میخ روز ۳۲ یک باگ ورودی است، نه تاریخ سررسید."""
    del seeded_policies
    admin = _admin("91")
    donor = _donor("91")
    campaign = _campaign(admin, slug_suffix="e91")

    with pytest.raises(DomainValidationError) as exc:
        _pledge_with_day(admin=admin, donor=donor, campaign=campaign, start_day=32)
    assert getattr(exc.value, "code", "") == "pledge_invalid_start_day"


def _pledge_with_day(*, admin: Any, donor: Any, campaign: Any, start_day: int) -> Any:
    return create_recurring_pledge(
        user=donor,
        benefactor=campaign.benefactor,
        target_kind=ContributionTargetKind.CAMPAIGN_SHARES,
        amount_rial=1_000_000,
        campaign=campaign,
        start_day=start_day,
    )


@pytest.mark.django_db
def test_pausing_a_cancelled_pledge_is_refused(seeded_policies: None) -> None:
    """تعهد لغو‌شده قابل توقف نیست — وضعیت‌ها باید سازگار بمانند."""
    del seeded_policies
    admin = _admin("92")
    donor = _donor("92")
    campaign = _campaign(admin, slug_suffix="e92")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge
    cancel_pledge(pledge_id=pledge.pk, user=donor)

    with pytest.raises(ConflictError) as exc:
        pause_pledge(pledge_id=pledge.pk, user=donor)
    assert getattr(exc.value, "code", "") == "pledge_not_pausable"


@pytest.mark.django_db
def test_resuming_an_active_pledge_is_refused(seeded_policies: None) -> None:
    """بازگرداندن تعهدی که متوقف نیست، خطاست — نه عملیات بی‌اثر."""
    del seeded_policies
    admin = _admin("93")
    donor = _donor("93")
    campaign = _campaign(admin, slug_suffix="e93")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge

    with pytest.raises(ConflictError) as exc:
        resume_pledge(pledge_id=pledge.pk, user=donor)
    assert getattr(exc.value, "code", "") == "pledge_not_paused"


@pytest.mark.django_db
def test_editing_a_cancelled_pledge_is_refused(seeded_policies: None) -> None:
    """تعهد لغو‌شده نباید مبلغش عوض شود — تاریخ مالی جعل می‌شد."""
    del seeded_policies
    admin = _admin("94")
    donor = _donor("94")
    campaign = _campaign(admin, slug_suffix="e94")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge
    cancel_pledge(pledge_id=pledge.pk, user=donor)

    with pytest.raises(ConflictError) as exc:
        update_pledge(pledge_id=pledge.pk, user=donor, amount_rial=5_000_000)
    assert getattr(exc.value, "code", "") == "pledge_not_editable"


@pytest.mark.django_db
def test_paid_installment_cannot_be_skipped(seeded_policies: None) -> None:
    """رد قسط پرداخت‌شده یعنی پاک‌کردن یک پرداخت واقعی — ممنوع."""
    del seeded_policies
    admin = _admin("95")
    donor = _donor("95")
    campaign = _campaign(admin, slug_suffix="e95")
    result = _pledge(admin=admin, donor=donor, campaign=campaign)
    PledgeInstallment.objects.filter(pk=result.first_installment.pk).update(
        status=InstallmentStatus.PAID
    )

    with pytest.raises(ConflictError) as exc:
        skip_installment(installment_id=result.first_installment.pk, user=donor)
    assert getattr(exc.value, "code", "") == "installment_already_paid"


@pytest.mark.django_db
def test_unknown_installment_raises_not_found(seeded_policies: None) -> None:
    """شناسهٔ ناموجود باید ۴۰۴ بدهد، نه خطای پایگاه داده."""
    del seeded_policies
    import uuid as uuid_mod

    _admin("96")
    donor = _donor("96")

    with pytest.raises(NotFoundError):
        skip_installment(installment_id=uuid_mod.uuid4(), user=donor)


@pytest.mark.django_db
def test_editing_frequency_updates_interval_months(seeded_policies: None) -> None:
    """تغییر تناوب باید فاصلهٔ ماهانه را هم عوض کند، نه فقط برچسب را."""
    del seeded_policies
    admin = _admin("97")
    donor = _donor("97")
    campaign = _campaign(admin, slug_suffix="e97")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge

    update_pledge(pledge_id=pledge.pk, user=donor, frequency=PledgeFrequency.QUARTERLY)

    pledge.refresh_from_db()
    assert pledge.frequency == PledgeFrequency.QUARTERLY
    assert pledge.interval_months == 3


@pytest.mark.django_db
def test_changing_start_day_moves_next_due_date(seeded_policies: None) -> None:
    """میخ روز جدید باید سررسید بعدی را بازمحاسبه کند."""
    del seeded_policies
    admin = _admin("98")
    donor = _donor("98")
    campaign = _campaign(admin, slug_suffix="e98")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge

    update_pledge(pledge_id=pledge.pk, user=donor, start_day=1)

    pledge.refresh_from_db()
    assert pledge.anchor_day == 1
    assert pledge.next_due_date.day == 1


@pytest.mark.django_db
def test_reminder_skips_non_active_pledge(seeded_policies: None) -> None:
    """تعهد متوقف نباید پیامک یادآوری بگیرد."""
    del seeded_policies
    admin = _admin("99")
    donor = _donor("99")
    campaign = _campaign(admin, slug_suffix="e99")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge
    materialize_due_installments(as_of=pledge.next_due_date)
    pause_pledge(pledge_id=pledge.pk, user=donor)
    # قسط سررسیدشده را دستی بازگردان تا تابع آن را ببیند
    PledgeInstallment.objects.filter(pledge=pledge, sequence=2).update(
        status=InstallmentStatus.SCHEDULED
    )

    noon = timezone.localtime(tehran_now_factory()).replace(hour=12, minute=0)
    stats = dispatch_pledge_reminders(now=noon)

    assert stats.sent == 0


@pytest.mark.django_db
def test_failed_sibling_does_not_abort_batch(seeded_policies: None) -> None:
    """یک تعهد معیوب نباید بقیهٔ دسته را از تولید قسط محروم کند."""
    del seeded_policies
    admin = _admin("10")
    donor_a = _donor("10")
    donor_b = _donor("11")
    campaign = _campaign(admin, slug_suffix="e10")
    good = _pledge(admin=admin, donor=donor_a, campaign=campaign).pledge
    # تعهد دوم را با تاریخ سررسید یکسان می‌سازیم تا در همان دسته باشد
    _pledge(admin=admin, donor=donor_b, campaign=campaign)

    stats = materialize_due_installments(as_of=good.next_due_date)

    assert stats.scanned >= 2
    assert stats.errors == 0
    assert stats.installments_created >= 2


# ══════════════════════════════════════════════════════════════════════════════
# ۱۲) اتصال به checkout واقعی و مسیرهای API باقی‌مانده
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_pay_installment_uses_real_checkout_and_links(seeded_policies: None) -> None:
    """**تست یکپارچگی کلیدی.**

    پرداخت قسط باید از checkout موجود عبور کند و در پایان یک تعهد↔مشارکت↔قسط
    کامل بسازد. اگر این بشکند، خیر پول می‌دهد ولی قسطش تسویه نمی‌شود.
    """
    del seeded_policies
    admin = _admin("11")
    donor = _donor("12")
    campaign = _campaign(admin, slug_suffix="chk1")
    result = _pledge(admin=admin, donor=donor, campaign=campaign, amount=1_000_000)

    payload = pay_installment(installment_id=result.first_installment.pk, user=donor)

    assert payload["contribution_id"]
    assert payload["payment_id"]
    assert payload["redirect_url"]
    contribution = Contribution.objects.get(pk=payload["contribution_id"])
    assert contribution.pledge_id == result.pledge.pk
    result.first_installment.refresh_from_db()
    assert result.first_installment.contribution_id == contribution.pk
    # هنوز پرداخت‌نشده — چون درگاه تأیید نکرده
    assert result.first_installment.status != InstallmentStatus.PAID


@pytest.mark.django_db
def test_callback_verification_settles_installment_end_to_end(seeded_policies: None) -> None:
    """زنجیرهٔ کامل: پرداخت قسط → تأیید درگاه → قسط PAID. بدون دستکاری دستی."""
    del seeded_policies
    from apps.contributions.services import verify_payment_callback

    admin = _admin("12")
    donor = _donor("13")
    campaign = _campaign(admin, slug_suffix="chk2")
    result = _pledge(admin=admin, donor=donor, campaign=campaign, amount=1_000_000)
    payload = pay_installment(installment_id=result.first_installment.pk, user=donor)

    from apps.contributions.models import Payment

    payment = Payment.objects.get(pk=payload["payment_id"])
    verify_payment_callback(authority=payment.authority, gateway_status="OK")

    result.first_installment.refresh_from_db()
    assert result.first_installment.status == InstallmentStatus.PAID
    result.pledge.refresh_from_db()
    assert result.pledge.installments_paid == 1
    assert result.pledge.total_paid_rial == 1_000_000


@pytest.mark.django_db
def test_api_patch_edits_amount(seeded_policies: None) -> None:
    """ویرایش مبلغ از API باید اثر کند و قسط باز را هم هم‌راستا کند."""
    del seeded_policies
    from tests.conftest import issue_client_for_user

    admin = _admin("13")
    donor = _donor("14")
    campaign = _campaign(admin, slug_suffix="api13")
    result = _pledge(admin=admin, donor=donor, campaign=campaign)
    client, _tokens = issue_client_for_user(donor)

    response = client.patch(
        f"/api/v1/me/pledges/{result.pledge.pk}",
        {"amount_rial": 250_000},
        format="json",
    )

    assert response.status_code == 200, response.content
    assert response.json()["amount_rial"] == 250_000
    result.first_installment.refresh_from_db()
    assert result.first_installment.amount_rial == 250_000


@pytest.mark.django_db
def test_api_delete_cancels_pledge(seeded_policies: None) -> None:
    """لغو از API باید وضعیت را تغییر دهد و دلیل را ذخیره کند."""
    del seeded_policies
    from tests.conftest import issue_client_for_user

    admin = _admin("14")
    donor = _donor("15")
    campaign = _campaign(admin, slug_suffix="api14")
    result = _pledge(admin=admin, donor=donor, campaign=campaign)
    client, _tokens = issue_client_for_user(donor)

    response = client.delete(
        f"/api/v1/me/pledges/{result.pledge.pk}",
        {"reason": "too_expensive"},
        format="json",
    )

    assert response.status_code == 200, response.content
    assert response.json()["status"] == "cancelled"
    result.pledge.refresh_from_db()
    assert result.pledge.cancel_reason == "too_expensive"


@pytest.mark.django_db
def test_api_installments_list_returns_all(seeded_policies: None) -> None:
    """فهرست اقساط باید شماره، مبلغ و پرچم قابل‌پرداخت را برگرداند."""
    del seeded_policies
    from tests.conftest import issue_client_for_user

    admin = _admin("15")
    donor = _donor("16")
    campaign = _campaign(admin, slug_suffix="api15")
    result = _pledge(admin=admin, donor=donor, campaign=campaign)
    client, _tokens = issue_client_for_user(donor)

    response = client.get(f"/api/v1/me/pledges/{result.pledge.pk}/installments")

    assert response.status_code == 200, response.content
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["sequence"] == 1
    assert rows[0]["amount_toman"] == 100_000
    assert rows[0]["can_pay"] is True


@pytest.mark.django_db
def test_api_list_filters_by_status(seeded_policies: None) -> None:
    """فیلتر وضعیت باید کار کند، وگرنه خیر باید همه را دستی بگردد."""
    del seeded_policies
    from tests.conftest import issue_client_for_user

    admin = _admin("16")
    donor = _donor("17")
    campaign = _campaign(admin, slug_suffix="api16")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge
    cancel_pledge(pledge_id=pledge.pk, user=donor)
    client, _tokens = issue_client_for_user(donor)

    active = client.get("/api/v1/me/pledges?status=active").json()
    cancelled = client.get("/api/v1/me/pledges?status=cancelled").json()

    assert active == []
    assert len(cancelled) == 1


@pytest.mark.django_db
def test_api_requires_authentication() -> None:
    """بدون ورود، حتی فهرست تعهدها هم نباید در دسترس باشد."""
    from rest_framework.test import APIClient

    client = APIClient()
    assert client.get("/api/v1/me/pledges").status_code == 401


@pytest.mark.django_db
def test_admin_stats_rejects_non_staff(seeded_policies: None) -> None:
    """خیر عادی نباید آمار کل خیریه را ببیند."""
    del seeded_policies
    from tests.conftest import issue_client_for_user

    donor = _donor("18")
    client, _tokens = issue_client_for_user(donor)

    assert client.get("/api/v1/admin/pledges/stats").status_code in {403, 401}


@pytest.mark.django_db
def test_admin_run_cycle_executes_all_four_steps(seeded_policies: None) -> None:
    """اجرای دستی چرخه باید چهار بخش گزارش بدهد — شفاف، نه یک «OK» مبهم."""
    del seeded_policies
    from tests.conftest import issue_client_for_user

    admin = _admin("17")
    donor = _donor("19")
    campaign = _campaign(admin, slug_suffix="api17")
    _pledge(admin=admin, donor=donor, campaign=campaign)
    client, _tokens = issue_client_for_user(admin, mfa_fresh=True)

    response = client.post("/api/v1/admin/pledges/run-cycle", {}, format="json")

    assert response.status_code == 200, response.content
    body = response.json()
    assert set(body) == {"materialize", "reminders", "expiry", "resumed"}


# ══════════════════════════════════════════════════════════════════════════════
# ۱۳) شاخه‌های مرزی مدل سهم و گزارش‌ها
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_shares_count_drives_amount_when_given(seeded_policies: None) -> None:
    """اگر تعداد سهم داده شود، مبلغ از آن محاسبه می‌شود (منبع حقیقت = سهم)."""
    del seeded_policies
    admin = _admin("20")
    donor = _donor("20")
    campaign = _campaign(admin, slug_suffix="s20")

    result = create_recurring_pledge(
        user=donor,
        benefactor=campaign.benefactor,
        target_kind=ContributionTargetKind.CAMPAIGN_SHARES,
        amount_rial=1,  # نادیده گرفته می‌شود
        shares_count=3,
        campaign=campaign,
    )

    assert result.pledge.amount_rial == 3_000_000
    assert result.pledge.shares_count == 3


@pytest.mark.django_db
def test_non_multiple_amount_is_rejected(seeded_policies: None) -> None:
    """مبلغ غیرمضرب یعنی پرداخت ماه بعد شکست می‌خورد — باید همین‌جا رد شود."""
    del seeded_policies
    admin = _admin("21")
    donor = _donor("21")
    campaign = _campaign(admin, slug_suffix="s21")

    with pytest.raises(DomainValidationError) as exc:
        create_recurring_pledge(
            user=donor,
            benefactor=campaign.benefactor,
            target_kind=ContributionTargetKind.CAMPAIGN_SHARES,
            amount_rial=1_500_000,
            campaign=campaign,
        )
    assert getattr(exc.value, "code", "") == "pledge_amount_not_share_multiple"


@pytest.mark.django_db
def test_creation_result_serializes(seeded_policies: None) -> None:
    """گزارش ساخت تعهد باید قابل‌سریالایز باشد (برای لاگ و CLI)."""
    del seeded_policies
    admin = _admin("22")
    donor = _donor("22")
    campaign = _campaign(admin, slug_suffix="s22")

    payload = _pledge(admin=admin, donor=donor, campaign=campaign).as_dict()

    assert set(payload) == {"pledge_id", "status", "first_due_date", "amount_rial"}
    assert payload["status"] == "active"


@pytest.mark.django_db
def test_cycle_stats_serialize_with_all_keys(seeded_policies: None) -> None:
    """آمار چرخه باید همهٔ کلیدها را داشته باشد — پایش خودکار به آن‌ها تکیه می‌کند."""
    del seeded_policies
    payload = materialize_due_installments().as_dict()
    assert set(payload) == {
        "scanned",
        "installments_created",
        "pledges_advanced",
        "expired_installments",
        "pledges_expired",
        "paused_resumed",
        "errors",
    }


@pytest.mark.django_db
def test_reminder_stats_serialize(seeded_policies: None) -> None:
    """آمار یادآوری شامل پرچم پنجرهٔ ساعتی است، نه فقط تعداد."""
    del seeded_policies
    payload = dispatch_pledge_reminders().as_dict()
    assert "window_open" in payload
    assert "skipped_cap" in payload


# ══════════════════════════════════════════════════════════════════════════════
# ۱۴) فرمان کرون — تنها کدی که هر شب بی‌ناظر اجرا می‌شود
#
# چرا این بخش جدا است؟ چون ``run_pledge_cycle`` تنها چیزی است که در تولید
# هر روز ساعت ۱۰ بی‌آنکه کسی تماشا کند اجرا می‌شود. اگر آرگومان‌های
# ``--skip-reminders`` یا ``--only`` بشکنند، تا صبح فردا کسی نمی‌فهمد.
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_cycle_command_reports_all_four_steps(seeded_policies: None) -> None:
    """خروجی JSON باید هر چهار گام را داشته باشد — پایش خودکار به آن تکیه می‌کند."""
    del seeded_policies
    from io import StringIO

    from django.core.management import call_command

    buffer = StringIO()
    call_command("run_pledge_cycle", "--json", stdout=buffer)

    payload = json.loads(buffer.getvalue())
    assert set(payload) == {"resumed", "materialize", "reminders", "expiry"}
    assert isinstance(payload["resumed"], int)
    assert "installments_created" in payload["materialize"]
    assert "window_open" in payload["reminders"]


@pytest.mark.django_db
def test_cycle_command_skip_reminders_sends_nothing(seeded_policies: None) -> None:
    """``--skip-reminders`` باید واقعاً هیچ پیامکی نسازد، نه فقط گزارش ندهد.

    این مهم است: اپراتور در شرایط اضطراری این سوئیچ را می‌زند و انتظار دارد
    سیل پیامک متوقف شود. اگر فقط گزارش تغییر کند ولی پیامک برود، سوئیچ
    امنیتی دروغین است.
    """
    del seeded_policies
    from io import StringIO

    from django.core.management import call_command

    admin = _admin("30")
    donor = _donor("30")
    campaign = _campaign(admin, slug_suffix="cmd30")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge
    materialize_due_installments(as_of=pledge.next_due_date)

    before = OutboxMessage.objects.filter(event_type="sms.pledge_reminder").count()
    buffer = StringIO()
    call_command("run_pledge_cycle", "--skip-reminders", "--json", stdout=buffer)

    after = OutboxMessage.objects.filter(event_type="sms.pledge_reminder").count()
    assert after == before, "با --skip-reminders نباید هیچ پیامک یادآوری ساخته شود"
    assert json.loads(buffer.getvalue())["reminders"]["skipped"]


@pytest.mark.django_db
def test_cycle_command_only_materialize_touches_one_step(seeded_policies: None) -> None:
    """``--only`` باید تنها همان گام را اجرا و گزارش کند، نه بیشتر."""
    del seeded_policies
    from io import StringIO

    from django.core.management import call_command

    admin = _admin("31")
    donor = _donor("31")
    campaign = _campaign(admin, slug_suffix="cmd31")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge
    buffer = StringIO()

    call_command("run_pledge_cycle", "--only", "materialize", "--json", stdout=buffer)

    payload = json.loads(buffer.getvalue())
    assert set(payload) == {"materialize"}
    assert payload["materialize"]["installments_created"] >= 0
    # سررسید جلو رفته ⇒ نشانهٔ اینکه واقعاً اجرا شد
    pledge.refresh_from_db()
    assert pledge.next_due_date >= pledge.created_at.date()


@pytest.mark.django_db
def test_cycle_command_human_output_is_readable(seeded_policies: None) -> None:
    """خروجی غیر-JSON باید برای انسان خوانا باشد، نه یک dict خام."""
    del seeded_policies
    from io import StringIO

    from django.core.management import call_command

    buffer = StringIO()
    call_command("run_pledge_cycle", stdout=buffer)

    text = buffer.getvalue()
    assert "چرخهٔ تعهد مستمر اجرا شد" in text
    assert "materialize" in text
    assert "expiry" in text


@pytest.mark.django_db
def test_cycle_command_only_expire_does_not_create_installments(seeded_policies: None) -> None:
    """گام انقضا نباید قسط بسازد — تفکیک مسئولیت‌ها."""
    del seeded_policies
    from io import StringIO

    from django.core.management import call_command

    admin = _admin("32")
    donor = _donor("32")
    campaign = _campaign(admin, slug_suffix="cmd32")
    pledge = _pledge(admin=admin, donor=donor, campaign=campaign).pledge
    before_count = PledgeInstallment.objects.filter(pledge=pledge).count()
    buffer = StringIO()

    call_command("run_pledge_cycle", "--only", "expire", "--json", stdout=buffer)

    assert PledgeInstallment.objects.filter(pledge=pledge).count() == before_count
    assert set(json.loads(buffer.getvalue())) == {"expiry"}
