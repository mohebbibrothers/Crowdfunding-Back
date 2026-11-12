"""فرمان مقداردهی اولیهٔ تکرارپذیر سیاست‌ها، دسته‌بندی‌ها، خیریه‌ها، قلک‌ها و حرکت‌های نمونه."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.benefactors.models import Benefactor, CharityJar
from apps.campaigns.choices import CampaignStatus, CampaignUrgency
from apps.campaigns.models import (
    Campaign,
    CampaignCategory,
    CampaignImpactUpdate,
    MatchingGrant,
)
from apps.campaigns.services import sync_benefactor_campaign_counters
from apps.core.models import PolicyRule
from apps.core.policy import DEFAULT_POLICIES
from apps.identity.choices import UserRole
from apps.identity.models import User
from apps.identity.validators import compute_iban_check_digits


def _valid_iban(bban_22_digits: str) -> str:
    """ساخت شماره شبای معتبر ۲۶ کاراکتری ایران با رقم کنترلی استاندارد Mod-97."""
    chk = compute_iban_check_digits(bban_22_digits)
    return f"IR{chk}{bban_22_digits}"


class Command(BaseCommand):
    """مقداردهی اولیهٔ امن و تکرارپذیر داده‌های پایه و نمونه برای محیط توسعه و نمایش."""

    help = "ایجاد سیاست‌های پیش‌فرض، دسته‌بندی‌ها، خیریه‌ها، قلک‌های عام و حرکت‌های نمونه"

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        del args, options
        for spec in DEFAULT_POLICIES:
            PolicyRule.objects.get_or_create(
                key=spec.key,
                defaults={
                    "value_type": spec.value_type,
                    "raw_value": spec.default,
                    "description": spec.description,
                },
            )

        admin_user, _ = User.objects.get_or_create(
            phone="09120000001",
            defaults={
                "first_name": "راهبر",
                "last_name": "ارشد سامانه",
                "role": UserRole.SUPER_ADMIN,
                "is_staff": True,
                "is_superuser": True,
            },
        )

        categories_spec = [
            ("درمان و سلامت کودکان", "health-care", "heart-pulse", 10),
            ("آزادی زندانیان جرایم غیرعمد", "prisoners-release", "scale", 20),
            ("تأمین جهیزیه و آغاز زندگی", "marriage-support", "sparkles", 30),
            ("تحصیل و تجهیزات آموزشی", "education", "book-open", 40),
            ("مسکن و سرپناه محرومین", "housing", "home", 50),
        ]
        cats: dict[str, CampaignCategory] = {}
        for title, slug, icon, order in categories_spec:
            cat, _ = CampaignCategory.objects.get_or_create(
                slug=slug,
                defaults={"title": title, "icon_name": icon, "display_order": order},
            )
            cats[slug] = cat

        ben1, _ = Benefactor.objects.get_or_create(
            slug="mehrafarin-health",
            defaults={
                "name": "مؤسسه خیریه مهرآفرین سلامت کودکان",
                "registration_number": "۴۸۹۱۲",
                "province": "تهران",
                "city": "تهران",
                "short_bio": "تأمین هزینه جراحی و داروهای حیاتی کودکان کم‌برخوردار در سراسر کشور.",
                "iban": _valid_iban("0170000000012345678901"),
                "bank_holder_name": "مؤسسه خیریه مهرآفرین سلامت",
                "is_verified": True,
            },
        )
        ben2, _ = Benefactor.objects.get_or_create(
            slug="diyeh-omid",
            defaults={
                "name": "پویش مردمی رهایی و امید (زندانیان غیرعمد)",
                "registration_number": "۳۱۵۰۴",
                "province": "اصفهان",
                "city": "اصفهان",
                "short_bio": "بازگرداندن سرپرستان خانواده‌های گرفتار بدهی و حوادث کارگاهی به آغوش خانه.",
                "iban": _valid_iban("0120000000098765432109"),
                "bank_holder_name": "مؤسسه خیریه رهایی و امید",
                "is_verified": True,
            },
        )

        CharityJar.objects.get_or_create(
            slug="mehrafarin-general-jar",
            defaults={
                "benefactor": ben1,
                "title": "قلک عام اورژانس دارویی کودکان مهرآفرین",
                "short_code": "jmehr1",
                "description": "مشارکت آزاد با هر مبلغ دلخواه برای نسخه‌های فوری دارویی کودکان بیمار.",
                "monthly_goal_rial": 500_000_000,
            },
        )

        now = timezone.now()
        camp1, _ = Campaign.objects.get_or_create(
            slug="heart-surgery-little-zahra",
            defaults={
                "benefactor": ben1,
                "category": cats["health-care"],
                "title": "تأمین هزینه عمل جراحی قلب باز کودک ۷ ساله در سیستان",
                "short_code": "hrt701",
                "subtitle": "۲۰۰ سهم ۵۰ هزار تومانی برای بازگرداندن تپش سالم به قلب یک کودک.",
                "why_and_what": (
                    "پروندهٔ پزشکی توسط مددکاری بیمارستان تخصصی قلب تأیید شده و تاریخ اتاق عمل برای "
                    "هفته آینده رزرو شده است. تمام منابع مستقیماً به حساب بیمارستان و داروخانه تسویه می‌گردد."
                ),
                "province": "سیستان و بلوچستان",
                "city": "زاهدان",
                "total_shares": 200,
                "share_price_rial": 500_000,
                "target_amount_rial": 200 * 500_000,
                "status": CampaignStatus.ACTIVE,
                "urgency_level": CampaignUrgency.EMERGENCY,
                "is_featured": True,
                "ends_at": now + timedelta(days=14),
                "created_by": admin_user,
            },
        )
        MatchingGrant.objects.get_or_create(
            campaign=camp1,
            sponsor_name="بنیاد نیکوکاری سپهر دانش",
            defaults={
                "match_ratio": 1,
                "total_pool_shares": 60,
                "is_active": True,
            },
        )
        CampaignImpactUpdate.objects.get_or_create(
            campaign=camp1,
            title="تأیید نهایی پذیرش بیمارستان و نوبت جراحی",
            defaults={
                "body": "مدارک اکوکاردیوگرافی و پذیرش بیمارستان تکمیل و تخفیف مددکاری اخذ شد.",
                "progress_percent": 15,
                "published_by": admin_user,
            },
        )

        Campaign.objects.get_or_create(
            slug="release-father-workshop-debt",
            defaults={
                "benefactor": ben2,
                "category": cats["prisoners-release"],
                "title": "آزادی پدر دو فرزند از زندان (محکومیت مالی غیرعمد کارگاهی)",
                "short_code": "rel402",
                "subtitle": "۵۰۰ سهم ۱۰۰ هزار تومانی پس از گذشت ۴۰ درصد بدهی توسط شاکی پرونده.",
                "why_and_what": "با میانجی‌گری مددکاران، شاکی پرونده ۴۰٪ مبلغ را بخشیده و با تکمیل این ۵۰۰ سهم حکم آزادی صادر می‌شود.",
                "province": "اصفهان",
                "city": "کاشان",
                "total_shares": 500,
                "share_price_rial": 1_000_000,
                "target_amount_rial": 500 * 1_000_000,
                "status": CampaignStatus.ACTIVE,
                "urgency_level": CampaignUrgency.URGENT,
                "ends_at": now + timedelta(days=25),
                "created_by": admin_user,
            },
        )

        sync_benefactor_campaign_counters(benefactor_id=ben1.id)
        sync_benefactor_campaign_counters(benefactor_id=ben2.id)
        self.stdout.write(self.style.SUCCESS("Seed data initialized successfully."))
