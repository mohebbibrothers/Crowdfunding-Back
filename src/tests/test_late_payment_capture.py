"""تست‌های پایداری حلقهٔ وجه در سناریوی «پرداخت دیرهنگام» (Late Capture).

تاریخچه: این فایل نخست برای *اثبات* یک شکاف نوشته شد — پرداخت موفق پس از انقضای
رزرو، پول را نزد درگاه رها می‌کرد و هیچ رکوردی نمی‌ساخت. پس از پیاده‌سازی حلقهٔ
نجب وجه (``reconcile_abandoned_payments``)، این فایل به تست **ضد‌بازگشت** تبدیل
شد: اگر کسی دوباره مسیر را بشکند، همین‌جا قرمز می‌شود.

تفکیک مسئولیت:
    • این فایل  ⇒ «سناریوی کاربر گم‌شده در مرز رزرو/بازگشت»
    • test_capture_recovery.py ⇒ «موتور داوری، دفترکل و idempotency»
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
import pytest

from apps.benefactors.models import Benefactor
from apps.campaigns.models import Campaign, CampaignCategory, CampaignStatus
from apps.campaigns.services import create_campaign
from apps.contributions.models import Contribution, Payment
from apps.contributions.services import (
    initiate_contribution_checkout,
    release_expired_share_holds,
    verify_payment_callback,
)
from apps.core.errors import ConflictError
from apps.identity.models import User


def _admin() -> User:
    return User.objects.create_superuser(
        phone="09120007701", first_name="ادمین", last_name="پرداخت دیرهنگام"
    )


def _campaign(admin: User, *, total_shares: int = 10) -> Campaign:
    ben = Benefactor.objects.create(
        name="خیریه آزمون دیرهنگام", slug="late-pay-charity", is_verified=True, is_active=True
    )
    cat = CampaignCategory.objects.create(title="دستهٔ دیرهنگام", slug="late-pay-cat")
    return create_campaign(
        actor=admin,
        data={
            "benefactor_id": str(ben.id),
            "category_id": str(cat.id),
            "title": "حرکت آزمون پرداخت دیرهنگام",
            "slug": "late-pay-campaign",
            "subtitle": "زیرعنوان",
            "story": "داستان حرکت برای آزمون پرداخت دیرهنگام.",
            "province": "تهران",
            "city": "تهران",
            "total_shares": total_shares,
            "share_price_rial": 1_000_000,
            "status": CampaignStatus.ACTIVE,
        },
    )


@pytest.mark.django_db
def test_late_payment_after_hold_expiry_raises_conflict_and_loses_money(
    seeded_policies: None,
) -> None:
    """اگر ظرفیت حرکت پس از انقضا پر شده باشد، تأیید پرداخت با خطا شکست می‌خورد."""
    del seeded_policies
    admin = _admin()
    campaign = _campaign(admin, total_shares=2)
    donor = User.objects.create_user(phone="09120007702", first_name="حامی", last_name="آزمون")

    # ۱) حامی هر ۲ سهم را رزرو می‌کند و به درگاه می‌رود
    contribution, payment = initiate_contribution_checkout(
        user=donor,
        target_kind="campaign_shares",
        campaign_id=str(campaign.id),
        shares_count=2,
    )

    # ۲) کاربر گم می‌شود؛ رزرو منقضی و آزاد می‌شود (همان کاری که cron می‌کند)
    Contribution.objects.filter(pk=contribution.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    released = release_expired_share_holds(campaign_id=campaign.id)
    assert released == 1

    contribution.refresh_from_db()
    payment.refresh_from_db()
    assert contribution.status == "expired"
    assert payment.status == "abandoned"  # نه "failed": وضعیت پول نامعلوم است

    # ۳) سهم‌ها به شخص دیگری فروخته می‌شود (ظرفیت تکمیل)
    campaign.refresh_from_db()
    campaign.paid_shares = campaign.total_shares  # funded = paid + matched + external
    campaign.save(update_fields=["paid_shares", "updated_at"])

    # ۴) کاربر با پرداخت موفق برمی‌گردد ⇒ درگاه می‌گوید پول گرفته شده
    with pytest.raises(ConflictError):
        verify_payment_callback(authority=payment.authority, gateway_status="OK")

    # مسیر بازگشت مرورگر نمی‌تواند مستقیم تسویه کند (ظرفیت پر است) — درست است.
    # اما پول دیگر «گم» نمی‌شود: پرداخت در وضعیت ABANDONED منتظر داوری است و
    # موتور حلقهٔ نجات (test_capture_recovery.py) آن را به تعهد بازپرداخت می‌برد.
    contribution.refresh_from_db()
    payment.refresh_from_db()
    assert contribution.status == "expired"
    assert payment.status == "abandoned"  # نه "failed": وضعیت پول نامعلوم است


@pytest.mark.django_db
def test_late_payment_when_capacity_still_available_is_accepted(
    seeded_policies: None,
) -> None:
    """اگر ظرفیت هنوز آزاد باشد، پرداخت دیرهنگام *پذیرفته* می‌شود (مسیر خوش‌بینانه)."""
    del seeded_policies
    admin = _admin()
    campaign = _campaign(admin, total_shares=10)
    donor = User.objects.create_user(phone="09120007703", first_name="حامی۲", last_name="آزمون")

    contribution, payment = initiate_contribution_checkout(
        user=donor,
        target_kind="campaign_shares",
        campaign_id=str(campaign.id),
        shares_count=2,
    )
    Contribution.objects.filter(pk=contribution.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    release_expired_share_holds(campaign_id=campaign.id)

    verified_payment, receipt = verify_payment_callback(
        authority=payment.authority, gateway_status="OK"
    )
    contribution.refresh_from_db()
    verified_payment.refresh_from_db()

    assert verified_payment.status == "verified"
    assert contribution.status == "paid"
    assert receipt is not None
    campaign.refresh_from_db()
    assert campaign.funded_shares == 2


@pytest.mark.django_db
def test_no_orphan_payment_without_any_callback(
    seeded_policies: None,
) -> None:
    """اگر کاربر هرگز برنگردد، پرداخت باید در صف داوری خودکار دیده شود.

    پیش‌تر این حالت «پول نامرئی» بود. اکنون ``reconcile_abandoned_payments``
    آن را کشف می‌کند و بر اساس پاسخ واقعی درگاه تعیین تکلیف می‌کند.
    """
    del seeded_policies
    admin = _admin()
    campaign = _campaign(admin, total_shares=10)
    donor = User.objects.create_user(phone="09120007704", first_name="حامی۳", last_name="آزمون")

    contribution, payment = initiate_contribution_checkout(
        user=donor,
        target_kind="campaign_shares",
        campaign_id=str(campaign.id),
        shares_count=1,
    )
    # کاربر پول داد ولی هرگز به سایت برنگشت ⇒ هیچ callback‌ای فراخوانی نمی‌شود.
    Contribution.objects.filter(pk=contribution.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    release_expired_share_holds(campaign_id=campaign.id)

    payment.refresh_from_db()
    # دیگر «ناموفق» کورکورانه نیست: پرداخت در وضعیت «رها‌شده» ثبت می‌شود تا
    # فرمان reconcile_abandoned_payments آن را از درگاه استعلام کند.
    assert payment.status == "abandoned"
    assert payment.ref_id == ""
    assert Payment.objects.filter(status="abandoned", ref_id="").count() == 1
    # و در صف داوری دیده می‌شود (نه اینکه هیچ‌جا نباشد).
    from apps.contributions.services import reconcile_abandoned_payments

    # برای عبور از پنجرهٔ مهلت (recovery.grace_minutes) زمان ایجاد را به عقب می‌بریم.
    past = timezone.now() - timedelta(minutes=40)
    Payment.objects.filter(pk=payment.pk).update(created_at=past, updated_at=past)
    stats = reconcile_abandoned_payments(dry_run=True)
    assert stats["scanned"] >= 1
