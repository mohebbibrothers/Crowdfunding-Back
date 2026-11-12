"""آزمون‌های هویت، OTP، نشست دوگانه، چرخش رفرش‌توکن، TOTP کارکنان، RBAC و زنجیرهٔ هش Audit."""

from __future__ import annotations

from django.test import override_settings
import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditRecord
from apps.audit.services import create_audit_anchor, verify_anchors, verify_chain
from apps.core.crypto import decrypt_value
from apps.core.models import OutboxMessage
from apps.core.outbox import drain_outbox
from apps.identity.models import User
from apps.identity.totp import current_totp as generate_totp
from apps.notifications.models import SmsDeliveryLog
from tests.conftest import issue_client_for_user


@pytest.mark.django_db
@override_settings(EXPOSE_DEV_OTP_CODE=True)
def test_otp_login_dual_session_refresh_rotation_and_revocation(
    api_client: APIClient,
    seeded_policies: None,
) -> None:
    """جریان کامل OTP ۵ رقمی، ورود دوگانه، چرخش رفرش‌توکن، تشخیص سرقت توکن و ابطال نشست."""
    del seeded_policies
    # ۱. درخواست OTP با ارقام فارسی
    r1 = api_client.post(
        "/api/v1/auth/otp/request",
        data={"phone": "۰۹۱۲۹۹۹۸۸۷۷"},
        format="json",
    )
    assert r1.status_code == 202
    assert "dev_otp" not in r1.json()  # هرگز کد OTP در پاسخ HTTP نشت نمی‌کند

    outbox_msg = OutboxMessage.objects.filter(event_type="sms.otp_requested").latest("created_at")
    otp_code = str(outbox_msg.payload["code"])
    assert len(otp_code) == 5
    drain_outbox()
    assert SmsDeliveryLog.objects.count() >= 1

    # ۲. تأیید OTP و دریافت توکن + کوکی نشست
    r2 = api_client.post(
        "/api/v1/auth/otp/verify",
        data={"phone": "09129998877", "code": otp_code},
        format="json",
    )
    assert r2.status_code == 200
    tokens = r2.json()
    access_1 = tokens["access_token"]
    refresh_1 = tokens["refresh_token"]
    session_id = tokens["session_id"]

    authed = APIClient()
    authed.credentials(HTTP_AUTHORIZATION=f"Bearer {access_1}")

    # ۳. مشاهده و تکمیل پروفایل + رمزنگاری کد ملی در سکون
    me_patch = authed.patch(
        "/api/v1/me",
        data={
            "first_name": "زهرا",
            "last_name": "محمدی",
            "national_code": "0013524682",
            "province": "فارس",
            "city": "شیراز",
        },
        format="json",
    )
    assert me_patch.status_code == 200
    assert me_patch.json()["display_name"] == "زهرا محمدی"

    db_user = User.objects.get(phone="09129998877")
    assert db_user.national_code_encrypted != "0013524682"
    assert decrypt_value(db_user.national_code_encrypted) == "0013524682"
    assert "*" in db_user.get_national_code_masked()

    # ۴. چرخش رفرش‌توکن و مسدودسازی توکن قدیمی (تشخیص سرقت رفرش‌توکن!)
    rot = api_client.post(
        "/api/v1/auth/token/refresh", data={"refresh_token": refresh_1}, format="json"
    )
    assert rot.status_code == 200
    refresh_2 = rot.json()["refresh_token"]
    assert refresh_2 != refresh_1

    # استفاده مجدد از refresh_1 باید نشست را به‌دلیل سرقت احتمالی ابطال کند!
    replay = api_client.post(
        "/api/v1/auth/token/refresh", data={"refresh_token": refresh_1}, format="json"
    )
    assert replay.status_code == 401

    # اکنون توکن دسترسی قبلی همان نشست هم بلافاصله نامعتبر شده است!
    revoked_check = authed.get("/api/v1/me")
    assert revoked_check.status_code == 401
    assert session_id


@pytest.mark.django_db
def test_staff_totp_enrollment_step_up_rbac_and_audited_phone_reveal(
    donor_user: User,
    operator_user: User,
    finance_user: User,
    seeded_policies: None,
) -> None:
    """ثبت‌نام TOTP کارکنان، کدهای بازیابی، ماتریس RBAC و افشای ممیزی‌شدهٔ شماره تلفن خیر."""
    del seeded_policies
    # ۱. کاربر عادی خیر نباید به مسیرهای ادمین دسترسی داشته باشد
    donor_client, _ = issue_client_for_user(donor_user)
    assert donor_client.get("/api/v1/admin/users").status_code == 403

    # ۲. مدیر مالی پیش از فعال‌سازی MFA، از عملیات ادمین منع می‌شود
    fin_client, _ = issue_client_for_user(finance_user, mfa_fresh=False)
    blocked = fin_client.get("/api/v1/admin/users")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "mfa_required"

    # ۳. ثبت‌نام و تأیید TOTP استاندارد RFC 6238
    setup_resp = fin_client.post("/api/v1/auth/mfa/totp/setup")
    assert setup_resp.status_code == 200
    secret = setup_resp.json()["secret"]
    assert "<svg" in setup_resp.json()["qr_svg"]

    live_code = generate_totp(secret)
    confirm_resp = fin_client.post(
        "/api/v1/auth/mfa/totp/confirm", data={"code": live_code}, format="json"
    )
    assert confirm_resp.status_code == 200
    recovery_codes = confirm_resp.json()["recovery_codes"]
    assert len(recovery_codes) == 10

    # ۴. اکنون نشست دارای MFA تازه است و فهرست کاربران با شماره پوشانده دیده می‌شود
    users_resp = fin_client.get("/api/v1/admin/users")
    assert users_resp.status_code == 200
    results = users_resp.json()["results"]
    donor_row = next(r for r in results if r["id"] == str(donor_user.id))
    assert "***" in donor_row["masked_phone"]
    assert "phone" not in donor_row

    # ۵. افشای ممیزی‌شدهٔ شماره موبایل کامل خیر نیازمند دلیل اداری معتبر است
    reveal_resp = fin_client.post(
        f"/api/v1/admin/users/{donor_user.id}/reveal-phone",
        data={"reason": "هماهنگی تلفنی جهت ارسال رسید رسمی مالیاتی"},
        format="json",
    )
    assert reveal_resp.status_code == 200
    assert reveal_resp.json()["phone"] == donor_user.phone

    # ۶. اپراتور عادی اجازهٔ دسترسی به نقاط پایانی مالی حساس (مثل لنگر حسابرسی) را ندارد
    op_client, _ = issue_client_for_user(operator_user, mfa_fresh=True)
    assert op_client.get("/api/v1/admin/audit/verify").status_code == 403


@pytest.mark.django_db
def test_tamper_evident_audit_hash_chain_and_signed_anchors(
    finance_user: User,
    donor_user: User,
    seeded_policies: None,
) -> None:
    """زنجیرهٔ هش SHA-256 حسابرسی هرگونه دستکاری مستقیم در دیتابیس را در همان ردیف تشخیص می‌دهد."""
    del seeded_policies
    fin_client, _ = issue_client_for_user(finance_user, mfa_fresh=False)
    sec = fin_client.post("/api/v1/auth/mfa/totp/setup").json()["secret"]
    fin_client.post(
        "/api/v1/auth/mfa/totp/confirm", data={"code": generate_totp(sec)}, format="json"
    )
    fin_client.post(
        f"/api/v1/admin/users/{donor_user.id}/reveal-phone",
        data={"reason": "بررسی صحت زنجیره حسابرسی غیرقابل تغییر"},
        format="json",
    )

    ok, broken_seq = verify_chain()
    assert ok is True
    assert broken_seq is None

    anchor = create_audit_anchor()
    assert anchor.last_sequence >= 1
    anchors_ok, bad_ids = verify_anchors()
    assert anchors_ok is True
    assert bad_ids == []

    # بررسی از طریق API رسمی ممیزی
    verify_api = fin_client.get("/api/v1/admin/audit/verify")
    assert verify_api.status_code == 200
    assert verify_api.json()["chain_valid"] is True
    assert verify_api.json()["anchors_valid"] is True

    # شبیه‌سازی دستکاری مخرب مستقیم در جدول دیتابیس (SQL Update دور زدن مدل)
    target_rec = AuditRecord.objects.order_by("sequence").first()
    assert target_rec is not None
    AuditRecord.objects.filter(pk=target_rec.pk).update(reason="TAMPERED_IN_DB")

    ok_after, broken_after = verify_chain()
    assert ok_after is False
    assert broken_after == target_rec.sequence
