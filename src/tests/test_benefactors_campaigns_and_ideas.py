"""آزمون‌های دامنه‌های مددکاران، قلک عام، حرکت‌ها، پیوندک کوتاه، حامی مضاعف و گزارش تحقق میدانی."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
import pytest
from rest_framework.test import APIClient

from apps.benefactors.models import Benefactor, CharityJar
from apps.campaigns.choices import CampaignStatus, CampaignUrgency
from apps.campaigns.models import Campaign, CampaignCategory
from apps.campaigns.services import create_campaign, update_campaign
from apps.contributions.services import initiate_contribution_checkout, verify_payment_callback
from apps.core.outbox import drain_outbox
from apps.identity.models import User
from tests.conftest import issue_client_for_user, make_valid_iban


@pytest.mark.django_db
def test_benefactors_public_privacy_admin_crud_and_charity_jars(
    api_client: APIClient,
    sample_benefactor: Benefactor,
    sample_charity_jar: CharityJar,
    super_admin_user: User,
) -> None:
    """نماهای عمومی مددکار و قلک عام هیچ‌گاه شبای کامل را افشا نمی‌کنند و ادمین چرخه کامل دارد."""
    pub_list = api_client.get("/api/v1/benefactors")
    assert pub_list.status_code == 200
    b_json = pub_list.json()
    items = b_json["results"] if isinstance(b_json, dict) else b_json
    assert any(b["slug"] == sample_benefactor.slug for b in items)
    for b in items:
        assert "iban" not in b

    pub_detail = api_client.get(f"/api/v1/benefactors/{sample_benefactor.slug}")
    assert pub_detail.status_code == 200
    assert pub_detail.json()["name"] == sample_benefactor.name

    jars_list = api_client.get("/api/v1/jars")
    assert jars_list.status_code == 200
    j_json = jars_list.json()
    jar_items = j_json["results"] if isinstance(j_json, dict) else j_json
    assert any(j["slug"] == sample_charity_jar.slug for j in jar_items)

    # ادمین با MFA تازه قادر به ثبت مددکار جدید و مشاهده شبای پوشانده است
    admin_client, _ = issue_client_for_user(super_admin_user, mfa_fresh=True)
    create_resp = admin_client.post(
        "/api/v1/admin/benefactors",
        data={
            "name": "مؤسسه دارالاکرام کوثر",
            "slug": "darolekram-kowsar",
            "short_bio": "بورسیه تحصیلی دانش‌آموزان مستعد مناطق محروم",
            "iban": make_valid_iban("0170000000004455667788"),
            "province": "خراسان رضوی",
            "city": "مشهد",
            "is_verified": True,
        },
        format="json",
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["iban"].startswith("IR")

    # جلوگیری از حذف فیزیکی مددکار دارای قلک/حرکت فعال (غیرفعال‌سازی ایمن به جای حذف)
    del_safe = admin_client.delete(f"/api/v1/admin/benefactors/{sample_benefactor.id}")
    assert del_safe.status_code == 200
    assert del_safe.json()["deleted"] is False
    assert del_safe.json()["deactivated"] is True


@pytest.mark.django_db
def test_campaigns_fair_ranking_shortlinks_matching_grants_and_impact_updates(
    api_client: APIClient,
    active_campaign: Campaign,
    sample_benefactor: Benefactor,
    sample_category: CampaignCategory,
    donor_user: User,
    super_admin_user: User,
) -> None:
    """رتبه‌بندی منصفانه v2، پیوندک کوتاه (Idea #7)، حامی مضاعف (Idea #8) و گزارش تحقق (Idea #4)."""
    # ساخت یک حرکت عادی دوم با پیشرفت بیشتر برای آزمون رتبه‌بندی منصفانه
    second_camp = create_campaign(
        actor=super_admin_user,
        data={
            "benefactor_id": str(sample_benefactor.id),
            "category_id": str(sample_category.id),
            "title": "تجهیز کتابخانه روستایی",
            "slug": "rural-library",
            "why_and_what": "خرید ۲۰۰ جلد کتاب مرجع برای دانش‌آموزان روستا.",
            "urgency_level": CampaignUrgency.NORMAL,
            "total_shares": 10,
            "share_price_rial": 500_000,
            "ends_at": timezone.now() + timedelta(days=60),
        },
    )
    second_camp = update_campaign(
        actor=super_admin_user,
        campaign_id=str(second_camp.id),
        data={"status": CampaignStatus.ACTIVE},
    )
    Campaign.objects.filter(pk=second_camp.pk).update(
        paid_shares=8, collected_online_rial=4_000_000
    )

    # ۱. در مرتب‌سازی پیش‌فرض fair، حرکت اضطراری کم‌پیشرفت بالاتر از حرکت عادی ۸۰٪ قرار می‌گیرد
    list_resp = api_client.get("/api/v1/campaigns")
    assert list_resp.status_code == 200
    slugs = [c["slug"] for c in list_resp.json()["results"]]
    assert slugs.index(active_campaign.slug) < slugs.index(second_camp.slug)

    # ۲. پیوندک کوتاه ۶ کاراکتری (Idea #7)
    short_resp = api_client.get(f"/api/v1/short-links/{active_campaign.short_code}")
    assert short_resp.status_code == 200
    assert short_resp.json()["slug"] == active_campaign.slug

    # ۳. ثبت حامی مضاعف (Idea #8) توسط مدیر مالی/ارشد
    admin_client, _ = issue_client_for_user(super_admin_user, mfa_fresh=True)
    mg_resp = admin_client.post(
        f"/api/v1/admin/campaigns/{active_campaign.id}/matching-grants",
        data={
            "sponsor_name": "بنیاد نیکوکاری امید فردا",
            "total_pool_shares": 20,
            "match_ratio": 1,
        },
        format="json",
    )
    assert mg_resp.status_code == 201

    # ۴. مشارکت خیر روی حرکت دارای حامی مضاعف -> ۲ سهم خیر + ۲ سهم حامی مضاعف!
    _contrib, payment = initiate_contribution_checkout(
        user=donor_user,
        target_kind="campaign_shares",
        campaign_id=str(active_campaign.id),
        shares_count=2,
    )
    verify_payment_callback(authority=payment.authority, gateway_status="OK")
    active_campaign.refresh_from_db()
    assert active_campaign.paid_shares == 2
    assert active_campaign.matched_shares == 2
    assert active_campaign.funded_shares == 4
    assert active_campaign.status == CampaignStatus.ACTIVE

    # ۵. انتشار گزارش مصور تحقق حرکت (Idea #4) و ارسال اعلان خودکار Outbox به خیرین حرکت
    imp_resp = admin_client.post(
        f"/api/v1/admin/campaigns/{active_campaign.id}/impact-updates",
        data={
            "title": "بستری شدن کودک و انجام آزمایش‌های اولیه",
            "body": "به لطف مشارکت شما مرحله اول پذیرش بیمارستانی انجام شد.",
            "progress_percent": 35,
            "is_published": True,
        },
        format="json",
    )
    assert imp_resp.status_code == 201
    drain_outbox()

    # خیر در صندوق اعلان شخصی خود پیام گزارش میدانی را دریافت کرده است
    donor_client, _ = issue_client_for_user(donor_user)
    notifs = donor_client.get("/api/v1/me/notifications")
    assert notifs.status_code == 200
    assert len(notifs.json()["results"]) >= 1
    assert any("بستری شدن کودک" in item["title"] for item in notifs.json()["results"])
