"""آزمون‌های جامع پرداخت، رزرو سهم، مشارکت ۳۰ ثانیه‌ای، نیت‌نامه، درخت مرکل، دفتر کل، تفکیک وظایف و هم‌روندی واقعی MariaDB."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.db import close_old_connections
from django.test import override_settings
from django.utils import timezone
from hypothesis import given, settings as hyp_settings, strategies as st
import pytest
from rest_framework.test import APIClient

from apps.benefactors.models import Benefactor, CharityJar
from apps.campaigns.choices import CampaignStatus, CampaignUrgency
from apps.campaigns.models import Campaign, CampaignCategory
from apps.campaigns.services import create_campaign, update_campaign
from apps.contributions.merkle import (
    MerkleLeafInput,
    build_merkle_levels,
    compute_leaf_hash,
    generate_inclusion_proof,
    verify_inclusion_proof,
)
from apps.contributions.models import Contribution, DonationReceipt
from apps.contributions.services import (
    initiate_contribution_checkout,
    release_expired_share_holds,
    verify_payment_callback,
)
from apps.core.errors import ConflictError
from apps.identity.choices import UserRole
from apps.identity.models import User
from apps.ledger.models import JournalEntry
from apps.ledger.services import capture_financial_control_snapshot
from tests.conftest import issue_client_for_user


@given(
    amounts=st.lists(
        st.integers(min_value=10_000, max_value=500_000_000),
        min_size=1,
        max_size=25,
    )
)
@hyp_settings(max_examples=40, deadline=None)
def test_property_merkle_tree_inclusion_proofs_and_tamper_rejection(amounts: list[int]) -> None:
    """هر برگ در درخت مرکل RFC 6962 اثبات شمول معتبر دارد و کوچک‌ترین تغییر در مقدار یا برگ رد می‌شود."""
    leaves = [
        compute_leaf_hash(
            MerkleLeafInput(
                contribution_id=f"c-{idx}",
                receipt_verification_code=f"V-{idx:04d}",
                shares_count=(idx % 5) + 1,
                matched_shares=0,
                amount_rial=amt,
            ),
            secret_salt="test-merkle-salt",
        )
        for idx, amt in enumerate(amounts)
    ]
    levels = build_merkle_levels(leaves)
    root = levels[-1][0]

    for idx, leaf in enumerate(leaves):
        gen_root, proof = generate_inclusion_proof(leaves, idx)
        assert gen_root == root
        assert verify_inclusion_proof(
            leaf_hash=leaf,
            proof=proof,
            expected_root=root,
        )
        # دستکاری هش برگ باید اثبات را رد کند
        tampered_leaf = ("0" if leaf[0] != "0" else "1") + leaf[1:]
        assert not verify_inclusion_proof(
            leaf_hash=tampered_leaf,
            proof=proof,
            expected_root=root,
        )


@pytest.mark.django_db
@override_settings(EXPOSE_DEV_OTP_CODE=True)
def test_end_to_end_express_checkout_dedication_ambassador_merkle_and_dashboard(
    api_client: APIClient,
    active_campaign: Campaign,
    sample_charity_jar: CharityJar,
    donor_user: User,
) -> None:
    """جریان کامل: سفیر مهربانی + مشارکت ۳۰ ثانیه‌ای مهمان + نیت‌نامه بدون نشت مبلغ + گواهی مرکل + داشبورد خیر."""
    # ۱. خیر اول یک لینک سفیر مهربانی (Idea #7) برای حرکت می‌سازد
    amb_client, _ = issue_client_for_user(donor_user)
    amb_resp = amb_client.post(
        "/api/v1/me/ambassador-links",
        data={
            "campaign_id": str(active_campaign.id),
            "custom_note": "بیایید با هم این جراحی را تکمیل کنیم",
        },
        format="json",
    )
    assert amb_resp.status_code == 201
    amb_code = amb_resp.json()["code"]

    # کلیک روی لینک کوتاه سفیر شمارنده کلیک را افزایش می‌دهد
    click_resp = api_client.get(f"/api/v1/short-links/{amb_code}")
    assert click_resp.status_code == 200
    assert click_resp.json()["ambassador_code"] == amb_code

    # ۲. مهمان تازه‌وارد از مسیر مشارکت سریع ۳۰ ثانیه‌ای (Idea #1) همراه با نیت‌نامه (Idea #2) و ناشناس (Idea #3) وارد می‌شود
    exp_start = api_client.post(
        "/api/v1/contributions/express/start",
        data={
            "phone": "09124443322",
            "display_name": "حسین کریمی",
            "target_kind": "campaign_shares",
            "campaign_id": str(active_campaign.id),
            "shares_count": 3,
            "is_anonymous": True,
            "public_note": "شفای عاجل همه کودکان بیمار",
            "ambassador_code": amb_code,
            "dedication": {
                "intent_type": "in_memory",
                "honoree_name": "مرحومه حاجیه خانم فاطمه امینی",
                "message": "شادی روح مادران آسمانی",
                "sender_display_name": "فرزندان",
            },
        },
        format="json",
    )
    assert exp_start.status_code == 201
    intent_id = exp_start.json()["intent_id"]
    otp_code = exp_start.json()["dev_code"]

    exp_confirm = api_client.post(
        "/api/v1/contributions/express/confirm",
        data={"intent_id": intent_id, "code": otp_code},
        format="json",
    )
    assert exp_confirm.status_code == 201
    conf_data = exp_confirm.json()
    authority = conf_data["authority"]
    contribution_id = conf_data["contribution_id"]
    guest_access = conf_data["access_token"]

    # پیش از پرداخت، دیوار حامیان خالی است
    supporters_before = api_client.get(f"/api/v1/campaigns/{active_campaign.slug}/supporters")
    sb_json = supporters_before.json()
    assert (sb_json["results"] if isinstance(sb_json, dict) else sb_json) == []

    # ۳. بازگشت موفق از درگاه پرداخت (Callback)
    cb_resp = api_client.post(
        "/api/v1/payments/callback",
        data={"authority": authority, "status": "OK"},
        format="json",
    )
    assert cb_resp.status_code == 200
    receipt_vcode = cb_resp.json()["verification_code"]

    # ۴. بررسی دیوار حامیان: نام خیر ناشناس «خیر گمنام» است!
    supporters_after = api_client.get(f"/api/v1/campaigns/{active_campaign.slug}/supporters")
    sa_json = supporters_after.json()
    wall = sa_json["results"] if isinstance(sa_json, dict) else sa_json
    assert len(wall) == 1
    assert wall[0]["supporter_name"] == "خیر گمنام"
    assert wall[0]["shares_count"] == 3

    # ۵. استعلام عمومی اصالت رسید بدون نشت شماره تلفن خیر
    rec_pub = api_client.get(f"/api/v1/receipts/verify/{receipt_vcode}")
    assert rec_pub.status_code == 200
    assert rec_pub.json()["donor_display_name"] == "خیر گمنام"
    assert "phone" not in rec_pub.json()

    # ۶. بررسی گواهی عمومی نیت‌نامه (Idea #2): فاقد هرگونه مبلغ ریالی یا تومانی!
    guest_client = APIClient()
    guest_client.credentials(HTTP_AUTHORIZATION=f"Bearer {guest_access}")
    dash_resp = guest_client.get("/api/v1/me/dashboard")
    assert dash_resp.status_code == 200
    dash = dash_resp.json()
    assert dash["summary"]["total_contributed_rial"] == 1_500_000
    assert dash["summary"]["total_contributed_toman"] == 150_000
    ded_token = dash["recent_contributions"][0]["dedication_token"]
    assert ded_token

    cert_resp = api_client.get(f"/api/v1/dedications/{ded_token}")
    assert cert_resp.status_code == 200
    cert_body = cert_resp.json()
    assert cert_body["honoree_name"] == "مرحومه حاجیه خانم فاطمه امینی"
    assert "amount_rial" not in cert_body
    assert "amount_toman" not in cert_body

    # ۷. اثبات شفافیت درخت مرکل (Idea #5/6): تطابق گواهی خیر با ریشهٔ عمومی حرکت
    pub_snap = api_client.get(f"/api/v1/campaigns/{active_campaign.slug}/transparency")
    assert pub_snap.status_code == 200
    public_root = pub_snap.json()["merkle_anchor"]["merkle_root"]

    proof_resp = guest_client.get(f"/api/v1/me/contributions/{contribution_id}/merkle-proof")
    assert proof_resp.status_code == 200
    proof_payload = proof_resp.json()
    assert proof_payload["verified"] is True
    assert proof_payload["merkle_root"] == public_root

    # ۸. بررسی اعتبار سفیر مهربانی برای خیر اول و مشارکت در قلک عام با Idempotency-Key
    amb_dash = amb_client.get("/api/v1/me/dashboard").json()
    assert amb_dash["ambassador_impact"]["attributed_shares"] == 3
    assert amb_dash["ambassador_impact"]["attributed_amount_rial"] == 1_500_000

    jar_payload = {
        "target_kind": "charity_jar",
        "charity_jar_id": str(sample_charity_jar.id),
        "amount_rial": 250_000,
    }
    idem_1 = amb_client.post(
        "/api/v1/contributions/checkout",
        data=jar_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="idem-jar-001",
    )
    assert idem_1.status_code == 201
    idem_2 = amb_client.post(
        "/api/v1/contributions/checkout",
        data=jar_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="idem-jar-001",
    )
    assert idem_2.status_code == 201
    assert idem_2["X-Idempotent-Replayed"] == "true"
    assert idem_1.json()["payment_id"] == idem_2.json()["payment_id"]

    # ارسال بدنه متفاوت با همان Idempotency-Key باید خطای 409 بدهد
    idem_conflict = amb_client.post(
        "/api/v1/contributions/checkout",
        data={**jar_payload, "amount_rial": 500_000},
        format="json",
        HTTP_IDEMPOTENCY_KEY="idem-jar-001",
    )
    assert idem_conflict.status_code == 409


@pytest.mark.django_db
def test_double_entry_ledger_external_funding_maker_checker_reconciliation_and_refund(
    active_campaign: Campaign,
    donor_user: User,
    finance_user: User,
    second_finance_user: User,
) -> None:
    """تراز صفر-انحراف دفتر کل دوطرفه، مشارکت خارجی مجزا، تفکیک وظایف تسویه، مغایرت‌گیری شاپرک و استرداد."""
    fin1_client, _ = issue_client_for_user(finance_user, mfa_fresh=True)
    fin2_client, _ = issue_client_for_user(second_finance_user, mfa_fresh=True)

    # ۱. وصول آنلاین ۱۰ سهم (۵٬۰۰۰٬۰۰۰ ریال)
    _contrib, payment = initiate_contribution_checkout(
        user=donor_user,
        target_kind="campaign_shares",
        campaign_id=str(active_campaign.id),
        shares_count=10,
    )
    verify_payment_callback(authority=payment.authority, gateway_status="OK")
    payment.refresh_from_db()

    # ۲. ثبت ۵ سهم مشارکت خارجی آفلاین (Idea #6) -> در حساب انتظامی ثبت می‌شود و بدهی آنلاین را تغییر نمی‌دهد
    ext_resp = fin1_client.post(
        f"/api/v1/admin/campaigns/{active_campaign.id}/external-contributions",
        data={
            "shares_count": 5,
            "donor_display_name": "حواله بانکی اتاق بازرگانی",
            "reference_code": "WIRE-1405-991",
            "note": "واریز مستقیم به حساب مؤسسه طبق نامه رسمی",
        },
        format="json",
    )
    assert ext_resp.status_code == 201
    active_campaign.refresh_from_db()
    assert active_campaign.paid_shares == 10
    assert active_campaign.external_shares == 5
    assert active_campaign.collected_online_rial == 5_000_000
    assert active_campaign.external_amount_rial == 2_500_000

    # کنترل تراز صفر-انحراف دفتر کل
    snap1 = capture_financial_control_snapshot()
    assert snap1.is_balanced is True

    # ۳. تفکیک وظایف (Maker-Checker) در تسویه با مددکار: درخواست‌کننده نمی‌تواند خودش تأیید کند!
    disb_req = fin1_client.post(
        "/api/v1/admin/disbursements",
        data={
            "benefactor_id": str(active_campaign.benefactor_id),
            "campaign_id": str(active_campaign.id),
            "amount_rial": 2_000_000,
            "request_note": "قسط اول بیمارستان",
        },
        format="json",
    )
    assert disb_req.status_code == 201
    disb_id = disb_req.json()["id"]

    self_approve = fin1_client.post(
        f"/api/v1/admin/disbursements/{disb_id}/review",
        data={
            "approve": True,
            "reason": "تلاش تأیید توسط خود درخواست‌کننده",
            "bank_reference_number": "PAYA-SELF-000",
        },
        format="json",
    )
    assert self_approve.status_code in {403, 409}

    # مدیر مالی دوم تأیید چهارچشمی و ثبت شناسه پایا را انجام می‌دهد
    peer_approve = fin2_client.post(
        f"/api/v1/admin/disbursements/{disb_id}/review",
        data={
            "approve": True,
            "reason": "تأیید مستندات مالی بیمارستان توسط مدیر مالی دوم",
            "bank_reference_number": "PAYA-14050821-7788",
        },
        format="json",
    )
    assert peer_approve.status_code == 200
    assert capture_financial_control_snapshot().is_balanced is True

    # ۴. مغایرت‌گیری فایل تسویه شاپرک
    now = timezone.now()
    rec_resp = fin1_client.post(
        "/api/v1/admin/reconciliations",
        data={
            "gateway_name": "sandbox",
            "period_start": (now - timedelta(days=1)).isoformat(),
            "period_end": (now + timedelta(hours=1)).isoformat(),
            "rows": [
                {
                    "authority": payment.authority,
                    "ref_id": payment.ref_id,
                    "amount_rial": 5_000_000,
                },
                {
                    "authority": "SBX-UNKNOWN999",
                    "ref_id": "REF-000",
                    "amount_rial": 1_000_000,
                },
            ],
        },
        format="json",
    )
    assert rec_resp.status_code == 201
    assert rec_resp.json()["matched_count"] == 1
    assert rec_resp.json()["discrepancy_count"] == 1

    # ۵. استرداد تراکنش دوم و بررسی تراز کامل دفتر کل پس از استرداد
    c2, p2 = initiate_contribution_checkout(
        user=donor_user,
        target_kind="campaign_shares",
        campaign_id=str(active_campaign.id),
        shares_count=2,
    )
    verify_payment_callback(authority=p2.authority, gateway_status="OK")
    ref_resp = fin1_client.post(
        f"/api/v1/admin/payments/{p2.id}/refund",
        data={"reason": "درخواست کتبی خیر بابت ثبت تکراری"},
        format="json",
    )
    assert ref_resp.status_code in {200, 201}
    c2.refresh_from_db()
    assert c2.status == "refunded"
    assert capture_financial_control_snapshot().is_balanced is True

    # بررسی انقضای خودکار رزرو ۱۵ دقیقه‌ای
    c_hold, _ = initiate_contribution_checkout(
        user=donor_user,
        target_kind="campaign_shares",
        campaign_id=str(active_campaign.id),
        shares_count=4,
    )
    Contribution.objects.filter(pk=c_hold.pk).update(
        hold_expires_at=timezone.now() - timedelta(minutes=1)
    )
    released = release_expired_share_holds(campaign_id=active_campaign.id)
    assert released == 1


@pytest.mark.django_db(transaction=True)
def test_concurrency_last_share_checkout_and_double_payment_callback(
    seeded_policies: None,
) -> None:
    """آزمون هم‌روندی واقعی MariaDB با چند رشته موازی: جلوگیری ۱۰۰٪ از بیش‌فروشی سهم و ثبت مضاعف رسید."""
    del seeded_policies
    admin = User.objects.create_superuser(
        phone="09120001999", first_name="ادمین", last_name="هم‌روندی"
    )
    ben = Benefactor.objects.create(
        name="خیریه آزمون هم‌روندی",
        slug="conc-charity",
        is_verified=True,
        is_active=True,
    )
    cat = CampaignCategory.objects.create(title="آزمون هم‌روندی", slug="conc-cat")
    camp = create_campaign(
        actor=admin,
        data={
            "benefactor_id": str(ben.id),
            "category_id": str(cat.id),
            "title": "حرکت آزمون رقابت آخرین سهم",
            "slug": "conc-last-share",
            "why_and_what": "آزمون قفل ردیفی SELECT FOR UPDATE در MariaDB.",
            "urgency_level": CampaignUrgency.URGENT,
            "total_shares": 5,
            "share_price_rial": 100_000,
        },
    )
    camp = update_campaign(
        actor=admin,
        campaign_id=str(camp.id),
        data={"status": CampaignStatus.ACTIVE},
    )
    donors = [
        User.objects.create_user(phone=f"0919000001{i}", role=UserRole.DONOR) for i in range(6)
    ]

    # رقابت ۱: ۶ کاربر به‌طور هم‌زمان برای خرید کل ۵ سهم باقی‌مانده هجوم می‌آورند
    def _try_checkout(u: User) -> str:
        close_old_connections()
        try:
            _, pay = initiate_contribution_checkout(
                user=u,
                target_kind="campaign_shares",
                campaign_id=str(camp.id),
                shares_count=5,
            )
            return pay.authority
        except ConflictError:
            return "CONFLICT"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(_try_checkout, donors))

    winners = [o for o in outcomes if o != "CONFLICT"]
    conflicts = [o for o in outcomes if o == "CONFLICT"]
    assert len(winners) == 1, f"Expected exactly 1 winner for last 5 shares, got {outcomes}"
    assert len(conflicts) == 5

    camp.refresh_from_db()
    assert camp.reserved_shares == 5
    assert camp.remaining_shares == 0

    # رقابت ۲: ۶ کال‌بک موازی شاپرک روی همان تراکنش برنده ارسال می‌شوند -> فقط ۱ سند و ۱ رسید ثبت می‌شود!
    winning_authority = winners[0]

    def _hit_callback(_idx: int) -> str:
        close_old_connections()
        try:
            _, rec = verify_payment_callback(authority=winning_authority, gateway_status="OK")
            return rec.receipt_number if rec is not None else "NONE"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=6) as pool:
        receipt_nums = list(pool.map(_hit_callback, range(6)))

    assert len(set(receipt_nums)) == 1
    assert receipt_nums[0].startswith("CF-")

    camp.refresh_from_db()
    assert camp.paid_shares == 5
    assert camp.reserved_shares == 0
    assert DonationReceipt.objects.filter(contribution__campaign=camp).count() == 1
    assert JournalEntry.objects.filter(campaign=camp).count() == 1
    assert capture_financial_control_snapshot().is_balanced is True
