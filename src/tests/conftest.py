"""فیکسچرهای مشترک pytest برای آزمون‌های یکپارچگی، امنیتی و مالی روی MariaDB."""

from __future__ import annotations

from contextlib import suppress
from datetime import timedelta
from typing import Any

from django.core.cache import cache
from django.utils import timezone
import pytest
from rest_framework.test import APIClient

from apps.benefactors.models import Benefactor, CharityJar
from apps.benefactors.services import create_benefactor, create_charity_jar
from apps.campaigns.choices import CampaignStatus, CampaignUrgency
from apps.campaigns.models import Campaign, CampaignCategory
from apps.campaigns.services import create_campaign, create_category, update_campaign
from apps.core.models import PolicyRule
from apps.core.policy import DEFAULT_POLICIES
from apps.identity.choices import UserRole
from apps.identity.models import User, UserSession
from apps.identity.services import IssuedAuthTokens, establish_dual_session
from apps.identity.validators import compute_iban_check_digits


@pytest.fixture(autouse=True)
def _clean_cache_between_tests() -> Any:
    """پاک‌سازی کش پیش از هر تست برای جلوگیری از نشت شمارنده‌های محدودیت نرخ و Epoch."""
    with suppress(Exception):
        cache.clear()
    yield


@pytest.fixture
def seeded_policies(db: Any) -> None:
    """اطمینان از وجود سیاست‌های پایه در دیتابیس تست."""
    del db
    for p in DEFAULT_POLICIES:
        PolicyRule.objects.get_or_create(
            key=p.key,
            defaults={
                "value_type": p.value_type,
                "raw_value": p.default,
                "description": p.description,
            },
        )


def make_valid_iban(seed_22_digits: str = "0170000000001122334455") -> str:
    """ساخت شماره شبای ۲۶ کاراکتری معتبر ایران برای تست."""
    chk = compute_iban_check_digits(seed_22_digits)
    return f"IR{chk}{seed_22_digits}"


@pytest.fixture
def api_client() -> APIClient:
    """کلاینت خام DRF."""
    return APIClient()


@pytest.fixture
def donor_user(db: Any) -> User:
    """خیر نمونه."""
    del db
    return User.objects.create_user(
        phone="09121112233",
        first_name="علی",
        last_name="رضایی",
        province="تهران",
        city="تهران",
        role=UserRole.DONOR,
    )


@pytest.fixture
def second_donor_user(db: Any) -> User:
    """خیر دوم برای آزمون‌های سفیر و رقابت روی آخرین سهم."""
    del db
    return User.objects.create_user(
        phone="09123334455",
        first_name="مریم",
        last_name="احمدی",
        province="اصفهان",
        city="اصفهان",
        role=UserRole.DONOR,
    )


@pytest.fixture
def operator_user(db: Any) -> User:
    """اپراتور عملیاتی نمونه."""
    del db
    return User.objects.create_user(
        phone="09125556677",
        first_name="کارشناس",
        last_name="عملیات",
        role=UserRole.OPERATOR,
        is_staff=True,
    )


@pytest.fixture
def finance_user(db: Any) -> User:
    """مدیر مالی نمونه."""
    del db
    return User.objects.create_user(
        phone="09127778899",
        first_name="مدیر",
        last_name="مالی اول",
        role=UserRole.FINANCE_MANAGER,
        is_staff=True,
    )


@pytest.fixture
def second_finance_user(db: Any) -> User:
    """مدیر مالی دوم برای آزمون تفکیک وظایف (Maker-Checker)."""
    del db
    return User.objects.create_user(
        phone="09128889900",
        first_name="مدیر",
        last_name="مالی دوم",
        role=UserRole.FINANCE_MANAGER,
        is_staff=True,
    )


@pytest.fixture
def super_admin_user(db: Any) -> User:
    """مدیر ارشد سامانه."""
    del db
    return User.objects.create_superuser(
        phone="09120000009",
        first_name="راهبر",
        last_name="کل",
    )


def issue_client_for_user(
    user: User, *, mfa_fresh: bool = False
) -> tuple[APIClient, IssuedAuthTokens]:
    """صدور نشست دوگانه واقعی و کلاینت مجهز به توکن JWT برای کاربر داده‌شده."""
    from django.contrib.sessions.middleware import SessionMiddleware
    from django.test import RequestFactory

    rf = RequestFactory()
    req = rf.post(
        "/api/v1/auth/otp/verify", HTTP_USER_AGENT="PytestAgent/1.0", REMOTE_ADDR="127.0.0.1"
    )
    SessionMiddleware(lambda r: None).process_request(req)  # type: ignore[arg-type, return-value]
    req.session.save()

    bundle = establish_dual_session(user=user, request=req)
    if mfa_fresh:
        from apps.core.crypto import encrypt_value
        from apps.identity.models import StaffTotpDevice
        from apps.identity.totp import generate_totp_secret

        StaffTotpDevice.objects.update_or_create(
            user=user,
            defaults={
                "secret_encrypted": encrypt_value(generate_totp_secret()),
                "confirmed_at": timezone.now(),
            },
        )
        UserSession.objects.filter(pk=bundle.session.id).update(
            mfa_verified_at=timezone.now(),
            mfa_method="totp",
        )
        bundle.session.refresh_from_db()

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {bundle.access_token}")
    return client, bundle


@pytest.fixture
def sample_benefactor(seeded_policies: None, super_admin_user: User) -> Benefactor:
    """مددکار نمونه برای حرکت‌ها و قلک‌ها."""
    del seeded_policies
    return create_benefactor(
        actor=super_admin_user,
        data={
            "name": "مؤسسه خیریه مهر ماندگار",
            "slug": "mehr-mandegar",
            "short_bio": "تأمین جهیزیه، درمان و آزادی زندانیان جرائم غیرعمد",
            "registration_number": "REG-55441",
            "iban": make_valid_iban("0170000000009988776655"),
            "province": "تهران",
            "city": "تهران",
            "is_verified": True,
        },
    )


@pytest.fixture
def sample_charity_jar(sample_benefactor: Benefactor, super_admin_user: User) -> CharityJar:
    """قلک عام نمونه."""
    return create_charity_jar(
        actor=super_admin_user,
        data={
            "benefactor_id": str(sample_benefactor.id),
            "title": "قلک عام دستگیری فوری",
            "slug": "fori-jar",
            "description": "مشارکت آزاد خیرین از ۱۰٬۰۰۰ تومان",
            "min_amount_rial": 100_000,
            "max_amount_rial": 2_000_000_000,
        },
    )


@pytest.fixture
def sample_category(super_admin_user: User) -> CampaignCategory:
    """دسته‌بندی موضوعی نمونه."""
    return create_category(
        actor=super_admin_user,
        data={
            "title": "درمان کودکان",
            "slug": "medical-kids",
            "icon_name": "heart-pulse",
            "sort_order": 1,
        },
    )


@pytest.fixture
def active_campaign(
    sample_benefactor: Benefactor,
    sample_category: CampaignCategory,
    super_admin_user: User,
) -> Campaign:
    """حرکت فعال نمونه با ۱۰۰ سهم ۵۰۰٬۰۰۰ ریالی (۵۰٬۰۰۰ تومانی)."""
    camp = create_campaign(
        actor=super_admin_user,
        data={
            "benefactor_id": str(sample_benefactor.id),
            "category_id": str(sample_category.id),
            "title": "تأمین هزینه جراحی قلب کودک نیازمند",
            "slug": "heart-surgery-kid",
            "subtitle": "۱۰۰ سهم ۵۰ هزار تومانی برای بازگشت لبخند",
            "why_and_what": "شرح کامل مدارک بیمارستانی و تأییدیه مددکاری مؤسسه.",
            "province": "تهران",
            "city": "ری",
            "urgency_level": CampaignUrgency.EMERGENCY,
            "total_shares": 100,
            "share_price_rial": 500_000,
            "min_shares_per_order": 1,
            "max_shares_per_order": 50,
            "ends_at": timezone.now() + timedelta(days=20),
            "is_featured": True,
        },
    )
    return update_campaign(
        actor=super_admin_user,
        campaign_id=str(camp.id),
        data={"status": CampaignStatus.ACTIVE},
    )
