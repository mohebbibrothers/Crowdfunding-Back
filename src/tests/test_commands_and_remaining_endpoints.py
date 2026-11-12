"""آزمون‌های پوشش کامل فرمان‌های عملیاتی Cron، نقاط پایانی مدیریتی/عمومی باقی‌مانده، نشست‌ها، کدهای بازیابی و محافظت تغییرناپذیری مالی."""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import override_settings
import pytest
from rest_framework.response import Response
from rest_framework.test import APIClient

from apps.benefactors.models import Benefactor, CharityJar
from apps.campaigns.models import Campaign, CampaignCategory
from apps.contributions.services import initiate_contribution_checkout, verify_payment_callback
from apps.core.checks import check_production_hygiene
from apps.core.db.fields import conditional_key
from apps.core.deprecation import (
    attach_deprecation_headers,
    build_deprecation_headers,
    deprecated_endpoint,
)
from apps.identity.choices import UserRole
from apps.identity.models import AuthRiskSignal, User
from apps.identity.totp import current_totp
from apps.notifications.choices import UserNotificationKind
from apps.notifications.services import create_user_notification
from tests.conftest import issue_client_for_user


@pytest.mark.django_db
def test_operational_management_commands_end_to_end() -> None:
    """اجرای کامل هر ۴ فرمان عملیاتی Cron (`seed_demo_data`, `process_outbox`, `reap_expired`, `anchor_audit_chain`)."""
    out = StringIO()
    call_command("seed_demo_data", stdout=out)
    assert "Seed data initialized successfully" in out.getvalue()

    out_box = StringIO()
    call_command("process_outbox", stdout=out_box)
    assert "Outbox processed" in out_box.getvalue()

    out_reap = StringIO()
    call_command("reap_expired", stdout=out_reap)
    assert "Reaped:" in out_reap.getvalue()

    out_anchor = StringIO()
    call_command("anchor_audit_chain", stdout=out_anchor)
    assert "ledger_balanced=True" in out_anchor.getvalue()


def test_rfc8594_deprecation_headers_and_production_checks() -> None:
    """بررسی سازندهٔ هدرهای منسوخ‌سازی RFC 8594 و بررسی‌های امنیتی محیط تولید."""
    hdrs = build_deprecation_headers(
        sunset_http_date="Wed, 11 Nov 2027 00:00:00 GMT",
        successor_path="/api/v2/campaigns",
        docs_url="https://docs.example.org/deprecations",
    )
    assert hdrs["Deprecation"] == "true"
    assert "Sunset" in hdrs
    assert 'rel="successor-version"' in hdrs["Link"]

    resp = Response({"ok": True})
    attach_deprecation_headers(
        resp,
        sunset_http_date="Wed, 11 Nov 2027 00:00:00 GMT",
        successor_path="/api/v2/campaigns",
    )
    assert resp["Deprecation"] == "true"

    with override_settings(
        ENVIRONMENT="production",
        PAYMENT_PROVIDER="sandbox",
        FIELD_ENCRYPTION_KEY="short",
        CORS_ALLOWED_ORIGINS=["https://bad-origin.example/"],
    ):
        issues = check_production_hygiene(app_configs=None)
        assert len(issues) == 3

    from django.db import models
    from django.db.models import Q

    gen_field = conditional_key("slug", Q(deleted_at__isnull=True), models.CharField(max_length=50))
    assert gen_field.db_persist is False

    class _DummyView:
        @deprecated_endpoint(
            successor_path="/api/v2/items",
            sunset_http_date="Wed, 11 Nov 2027 00:00:00 GMT",
        )
        def get(self, request: object) -> Response:
            del request
            return Response({"legacy": True})

    dep_resp = _DummyView().get(object())
    assert dep_resp["Deprecation"] == "true"

    from django.http import HttpRequest, HttpResponse

    from apps.core.views import docs_protected_wrapper

    wrapped_docs = docs_protected_wrapper(lambda req: HttpResponse("ok"))
    req = HttpRequest()
    req.path = "/api/v1/docs"
    with override_settings(DEBUG=False, API_DOCS_ALLOW_ANONYMOUS=False):
        assert wrapped_docs(req).status_code == 302


@pytest.mark.django_db
def test_sessions_password_login_recovery_codes_risk_review_and_role_change(
    api_client: APIClient,
    donor_user: User,
    super_admin_user: User,
    seeded_policies: None,
) -> None:
    """ورود رمزعبور کارمندی، تایید کد بازیابی یک‌بارمصرف، مدیریت نشست‌ها، بررسی سیگنال ریسک و تغییر نقش."""
    del seeded_policies
    # تنظیم رمز عبور برای کارمند جدید و ورود با رمز عبور
    User.objects.create_user(
        phone="09126667788",
        password="StrongStaffPassword!2026",
        first_name="مسئول",
        last_name="پشتیبانی",
        role=UserRole.OPERATOR,
        is_staff=True,
    )
    pw_login = api_client.post(
        "/api/v1/auth/staff/password-login",
        data={"phone": "09126667788", "password": "StrongStaffPassword!2026"},
        format="json",
    )
    assert pw_login.status_code == 200
    assert pw_login.json()["mfa_required"] is True

    staff_client = APIClient()
    staff_client.credentials(HTTP_AUTHORIZATION=f"Bearer {pw_login.json()['access_token']}")

    # ثبت‌نام TOTP و استفاده از کد بازیابی یک‌بارمصرف روی نشست دوم
    setup = staff_client.post("/api/v1/auth/mfa/totp/setup").json()
    conf = staff_client.post(
        "/api/v1/auth/mfa/totp/confirm",
        data={"code": current_totp(setup["secret"])},
        format="json",
    ).json()
    recovery_code = conf["recovery_codes"][0]

    mfa_stat = staff_client.get("/api/v1/auth/mfa/status")
    assert mfa_stat.status_code == 200
    assert mfa_stat.json()["enrolled"] is True

    # نشست دوم با کد بازیابی MFA را تأیید می‌کند
    pw_login_2 = api_client.post(
        "/api/v1/auth/staff/password-login",
        data={"phone": "09126667788", "password": "StrongStaffPassword!2026"},
        format="json",
    ).json()
    staff_client_2 = APIClient()
    staff_client_2.credentials(HTTP_AUTHORIZATION=f"Bearer {pw_login_2['access_token']}")
    rec_verify = staff_client_2.post(
        "/api/v1/auth/mfa/verify",
        data={"code": recovery_code},
        format="json",
    )
    assert rec_verify.status_code == 200

    # فهرست نشست‌های فعال و ابطال نشست دیگر و خروج
    sessions_resp = staff_client_2.get("/api/v1/me/sessions")
    assert sessions_resp.status_code == 200
    assert len(sessions_resp.json()) >= 2

    other_sid = pw_login.json()["session_id"]
    rev_resp = staff_client_2.post(f"/api/v1/me/sessions/{other_sid}/revoke")
    assert rev_resp.status_code in {200, 204}

    assert staff_client_2.post("/api/v1/auth/logout-others").status_code in {200, 204}
    assert staff_client_2.post("/api/v1/auth/logout").status_code in {200, 204}

    # مدیریت نقش کاربری، سیگنال‌های ریسک، لاگ حسابرسی و سلامت تفصیلی توسط مدیر ارشد
    admin_client, _ = issue_client_for_user(super_admin_user, mfa_fresh=True)

    csrf_resp = api_client.get("/api/v1/auth/csrf")
    assert csrf_resp.status_code == 200

    with override_settings(METRICS_BEARER_TOKEN="prom-secret"):
        assert api_client.get("/metrics").status_code == 403
        assert (
            api_client.get(
                "/metrics",
                HTTP_AUTHORIZATION="Bearer prom-secret",
            ).status_code
            == 200
        )

    detailed_health = admin_client.get("/api/v1/health/detailed")
    assert detailed_health.status_code == 200

    audit_logs = admin_client.get("/api/v1/admin/audit/logs")
    assert audit_logs.status_code == 200
    assert len(audit_logs.json()["results"]) >= 1

    role_upd = admin_client.post(
        f"/api/v1/admin/users/{donor_user.id}/role",
        data={"role": UserRole.OPERATOR, "reason": "ارتقای آزمایشی به کارشناس عملیات"},
        format="json",
    )
    assert role_upd.status_code in {200, 405}
    if role_upd.status_code == 405:
        role_upd = admin_client.patch(
            f"/api/v1/admin/users/{donor_user.id}/role",
            data={"role": UserRole.OPERATOR, "reason": "ارتقای آزمایشی به کارشناس عملیات"},
            format="json",
        )
        assert role_upd.status_code == 200

    sig = AuthRiskSignal.objects.create(
        user=donor_user,
        signal_type="otp_brute_force",
        phone_masked=donor_user.masked_phone,
    )
    risks_list = admin_client.get("/api/v1/admin/auth/risk-signals")
    assert risks_list.status_code == 200
    rev_sig = admin_client.post(
        f"/api/v1/admin/auth/risk-signals/{sig.id}/review",
        data={"status": "resolved", "note": "بررسی شد و مورد مشکوکی نبود"},
        format="json",
    )
    assert rev_sig.status_code in {200, 422}


@pytest.mark.django_db
def test_remaining_public_and_admin_endpoints_and_financial_immutability(
    api_client: APIClient,
    active_campaign: Campaign,
    sample_benefactor: Benefactor,
    sample_charity_jar: CharityJar,
    sample_category: CampaignCategory,
    donor_user: User,
    super_admin_user: User,
) -> None:
    """پوشش کامل نقاط پایانی باقی‌مانده حرکت‌ها، قلک‌ها، اعلان‌ها، دفتر کل، Sandbox و محافظت تغییرناپذیری مالی."""
    del sample_category
    # نماهای عمومی دسته‌بندی، جزئیات حرکت با فیلترها و جزئیات قلک
    assert api_client.get("/api/v1/campaign-categories").status_code == 200
    assert api_client.get(f"/api/v1/campaigns/{active_campaign.slug}").status_code == 200
    assert api_client.get("/api/v1/campaigns?ordering=newest&urgency=emergency").status_code == 200
    assert api_client.get("/api/v1/campaigns?ordering=ending_soon&search=جراحی").status_code == 200
    assert api_client.get("/api/v1/campaigns?ordering=most_funded").status_code == 200
    assert api_client.get(f"/api/v1/jars/{sample_charity_jar.slug}").status_code == 200

    # مشارکت خیر، مشاهدهٔ جزئیات Sandbox، تاریخچهٔ من، تایید عمومی مرکل و خواندن اعلان‌ها
    donor_client, _ = issue_client_for_user(donor_user)
    contrib, payment = initiate_contribution_checkout(
        user=donor_user,
        target_kind="campaign_shares",
        campaign_id=str(active_campaign.id),
        shares_count=2,
    )
    sbx = api_client.get(f"/api/v1/payments/sandbox/{payment.authority}")
    assert sbx.status_code == 200

    verify_payment_callback(authority=payment.authority, gateway_status="OK")

    me_contribs = donor_client.get("/api/v1/me/contributions")
    assert me_contribs.status_code == 200
    assert len(me_contribs.json()["results"]) >= 1

    proof_data = donor_client.get(f"/api/v1/me/contributions/{contrib.id}/merkle-proof").json()
    pub_verify = api_client.post(
        "/api/v1/transparency/verify-proof",
        data={
            "leaf_hash": proof_data["leaf_hash"],
            "proof": proof_data["proof"],
            "merkle_root": proof_data["merkle_root"],
        },
        format="json",
    )
    assert pub_verify.status_code == 200
    assert pub_verify.json()["valid"] is True

    # خواندن اعلان تکی و خواندن همه اعلان‌ها
    notif = create_user_notification(
        user_id=donor_user.id,
        kind=UserNotificationKind.RECEIPT_READY,
        title="خوش‌آمدگویی",
        body="از همراهی شما سپاسگزاریم.",
    )
    assert donor_client.post(f"/api/v1/me/notifications/{notif.id}/read").status_code == 200
    assert donor_client.post("/api/v1/me/notifications/read-all").status_code == 200

    # مسیرهای مدیریتی دفتر کل، پرداخت‌ها، ویرایش خیریه/قلک و محافظت تغییرناپذیری مبلغ سهم پس از جذب وجه!
    admin_client, _ = issue_client_for_user(super_admin_user, mfa_fresh=True)
    assert admin_client.get("/api/v1/admin/ledger/accounts").status_code == 200
    assert admin_client.get("/api/v1/admin/ledger/entries").status_code == 200
    assert admin_client.post("/api/v1/admin/ledger/control-snapshot").status_code in {200, 201}
    assert admin_client.get("/api/v1/admin/disbursements").status_code == 200
    assert admin_client.get("/api/v1/admin/reconciliations").status_code == 200
    assert admin_client.get("/api/v1/admin/payments").status_code == 200
    assert admin_client.get("/api/v1/admin/campaigns").status_code == 200
    assert admin_client.get("/api/v1/admin/benefactors").status_code == 200
    assert admin_client.get("/api/v1/admin/jars").status_code == 200

    assert (
        admin_client.patch(
            f"/api/v1/admin/benefactors/{sample_benefactor.id}",
            data={"short_bio": "بیوگرافی به‌روزشده خیریه"},
            format="json",
        ).status_code
        == 200
    )
    assert (
        admin_client.patch(
            f"/api/v1/admin/jars/{sample_charity_jar.id}",
            data={"description": "توضیح به‌روزشده قلک عام"},
            format="json",
        ).status_code
        == 200
    )

    # تلاش برای تغییر قیمت هر سهم پس از ثبت پرداخت قطعی باید با ۴۰۹ مسدود شود!
    imm_conflict = admin_client.patch(
        f"/api/v1/admin/campaigns/{active_campaign.id}",
        data={"share_price_rial": 900_000},
        format="json",
    )
    assert imm_conflict.status_code == 409


@pytest.mark.django_db
def test_jalali_money_db_cache_and_admin_lifecycle_crud(
    super_admin_user: User,
) -> None:
    """پوشش کامل تبدیل دوطرفهٔ تاریخ شمسی، اعتبارسنجی ریال/تومان، کش اتمیک دیتابیس و چرخهٔ کامل ساخت مدیریتی."""
    from datetime import UTC, datetime

    from apps.core.jalali import (
        format_jalali_date,
        format_jalali_datetime,
        gregorian_to_jalali,
        jalali_to_gregorian,
    )
    from apps.core.money import MoneyPair, assert_positive_rial, money_fields, rial_to_toman

    # تبدیل دوطرفه جلالی <-> میلادی و قالب‌بندی زمانی
    g_date = jalali_to_gregorian(1405, 8, 21)
    assert gregorian_to_jalali(g_date.year, g_date.month, g_date.day) == (1405, 8, 21)
    assert format_jalali_date(None) is None
    assert format_jalali_datetime(None) is None
    now_dt = datetime(2026, 11, 12, 10, 30, tzinfo=UTC)
    assert format_jalali_date(now_dt) == "1405-08-21"
    assert format_jalali_datetime(now_dt) is not None

    with pytest.raises(ValueError):
        jalali_to_gregorian(1405, 7, 31)

    # محاسبات دقیق ریال و تومان و رد اعداد غیرمضرب ۱۰ یا غیرصحیح
    pair = MoneyPair(250_000)
    assert pair.as_dict() == {"rial": 250_000, "toman": 25_000}
    assert rial_to_toman(-50_000) == -5_000
    assert money_fields("goal", 100_000)["goal_toman"] == 10_000
    assert assert_positive_rial(100_000) == 100_000
    with pytest.raises(TypeError):
        MoneyPair(True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        assert_positive_rial(105)
    with pytest.raises(ValueError):
        assert_positive_rial(0)

    # چرخهٔ کامل ساخت و حذف مدیریتی دسته‌بندی، خیریه، قلک و حرکت بدون جذب وجه
    admin_client, _ = issue_client_for_user(super_admin_user, mfa_fresh=True)

    cat_resp = admin_client.post(
        "/api/v1/admin/campaign-categories",
        data={"title": "آبرسانی روستایی", "slug": "rural-water-supply", "display_order": 5},
        format="json",
    )
    assert cat_resp.status_code == 201
    cat_id = cat_resp.json()["id"]

    ben_resp = admin_client.post(
        "/api/v1/admin/benefactors",
        data={
            "name": "موسسه جهادی کوثر",
            "slug": "kowsar-charity",
            "registration_number": "998811",
            "iban": "IR062960000000100324200001",
            "short_bio": "خدمت‌رسانی به مناطق کم‌برخوردار",
        },
        format="json",
    )
    assert ben_resp.status_code == 201
    ben_id = ben_resp.json()["id"]

    # ساخت حرکت جدید، ویرایش مجاز (قبل از جذب وجه) و توقف موقت حرکت
    camp_resp = admin_client.post(
        "/api/v1/admin/campaigns",
        data={
            "benefactor_id": ben_id,
            "category_id": cat_id,
            "title": "احداث مخزن آب شرب روستا",
            "slug": "village-water-tank",
            "subtitle": "تامین آب شرب پایدار برای ۱۲۰ خانوار",
            "why_and_what": "شرح کامل پروژه آبرسانی با نظارت مهندسین داوطلب.",
            "share_price_rial": 500_000,
            "total_shares": 40,
            "status": "active",
            "urgency_level": "urgent",
            "province": "سیستان و بلوچستان",
            "city": "سراوان",
            "media_items": [
                {
                    "kind": "image",
                    "url": "https://cdn.example.org/water.jpg",
                    "caption": "محل احداث مخزن",
                }
            ],
        },
        format="json",
    )
    assert camp_resp.status_code == 201
    camp_id = camp_resp.json()["id"]

    patch_ok = admin_client.patch(
        f"/api/v1/admin/campaigns/{camp_id}",
        data={
            "share_price_rial": 600_000,
            "title": "احداث مخزن آب شرب روستای نمونه",
            "status": "paused",
            "urgency_level": "emergency",
            "is_featured": True,
            "reason": "بازنگری نقشه فنی",
        },
        format="json",
    )
    assert patch_ok.status_code == 200
    assert patch_ok.json()["share_price_rial"] == 600_000

    # ساخت قلک جدید و حذف نرم خیریهٔ بدون وابستگی مالی
    jar_resp = admin_client.post(
        "/api/v1/admin/jars",
        data={
            "benefactor_id": ben_id,
            "title": "قلک مهربانی کوثر",
            "slug": "kowsar-jar",
            "description": "کمک‌های خرد مستمر",
            "min_amount_rial": 100_000,
        },
        format="json",
    )
    assert jar_resp.status_code == 201
    jar_id = jar_resp.json()["id"]
    assert (
        admin_client.patch(
            f"/api/v1/admin/jars/{jar_id}",
            data={"is_active": False},
            format="json",
        ).status_code
        == 200
    )

    ben_unused = admin_client.post(
        "/api/v1/admin/benefactors",
        data={
            "name": "خیریه موقت بدون حرکت",
            "slug": "temp-unused-charity",
            "registration_number": "112233",
            "iban": "IR062960000000100324200001",
        },
        format="json",
    ).json()
    del_unused = admin_client.delete(f"/api/v1/admin/benefactors/{ben_unused['id']}")
    assert del_unused.status_code in {200, 204}


@pytest.mark.django_db(transaction=True, databases=["default", "cache"])
def test_atomic_database_cache_and_external_http_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    """تست اتمیک کش MariaDB و آداپتورهای HTTPS زرین‌پال و پیامک الگومحور با شبیه‌سازی شبکه."""
    from typing import Any
    from unittest.mock import MagicMock

    from django.db import connections

    from apps.contributions.gateways import ZarinpalGatewayAdapter
    from apps.core.db.cache import AtomicDatabaseCache
    from apps.notifications.providers import HttpPatternSmsAdapter

    call_command("createcachetable", "django_cache_test", database="cache")
    try:
        db_cache = AtomicDatabaseCache("django_cache_test", {})
        db_cache.set("epoch_counter", 10, timeout=300)
        assert db_cache.incr("epoch_counter", 5) == 15
        assert db_cache.decr("epoch_counter", 2) == 13
        with pytest.raises(ValueError):
            db_cache.incr("missing_counter_key")
    finally:
        with connections["cache"].cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS `django_cache_test`")

    # تست آداپتور زرین‌پال و آداپتور پیامک الگومحور با شبیه‌سازی امن httpx.Client
    monkeypatch.setattr("apps.contributions.gateways.assert_safe_endpoint", lambda u, **kw: u)
    monkeypatch.setattr("apps.notifications.providers.assert_safe_endpoint", lambda u, **kw: u)

    mock_resp = MagicMock()
    mock_resp.content = b'{"ok":true}'
    mock_resp.json.return_value = {
        "message_id": "MSG-9001",
        "data": {
            "code": 100,
            "authority": "A00000000000000000000000000123456789",
            "ref_id": 778899,
            "card_pan": "603799******1234",
        },
    }
    mock_client_ctx = MagicMock()
    mock_client_ctx.__enter__.return_value.post.return_value = mock_resp

    monkeypatch.setattr("httpx.Client", lambda **kw: mock_client_ctx)

    zp = ZarinpalGatewayAdapter(
        merchant_id="00000000-0000-0000-0000-000000000000",
        request_url="https://payment.zarinpal.com/pg/v4/payment/request.json",
        verify_url="https://payment.zarinpal.com/pg/v4/payment/verify.json",
        startpay_base="https://payment.zarinpal.com/pg/StartPay",
    )
    init_res = zp.initiate(
        amount_rial=500_000,
        callback_url="https://charity.example.org/cb",
        description="تست درگاه",
        mobile="09121112233",
    )
    assert init_res.authority.startswith("A000")
    ver_res = zp.verify(authority=init_res.authority, amount_rial=500_000)
    assert ver_res.verified is True
    assert ver_res.ref_id == "778899"

    sms_adapter = HttpPatternSmsAdapter(
        provider_name="iranpayamak",
        endpoint_url="https://sms.example.org/v1/send",
        api_key="test-key",
        pattern_map={"otp_login": "PAT-101"},
    )
    sms_res: Any = sms_adapter.send_pattern(
        phone="09121112233",
        pattern_key="otp_login",
        tokens={"code": "12345"},
    )
    assert sms_res.delivered is True
    assert sms_res.message_id == "MSG-9001"
