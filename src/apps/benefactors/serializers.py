"""سریالایزرهای خیریه‌ها و قلک‌های عام با نمایش دوگانهٔ ریال/تومان."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.benefactors.models import Benefactor, CharityJar
from apps.core.jalali import format_jalali_datetime
from apps.core.money import rial_to_toman
from apps.core.policy import is_feature_enabled


class CharityJarPublicSerializer(serializers.Serializer[Any]):
    """نمای عمومی قلک عام خیریه با نمایش ریال و تومان."""

    id = serializers.UUIDField()
    benefactor_id = serializers.UUIDField()
    benefactor_name = serializers.CharField(source="benefactor.name")
    benefactor_slug = serializers.CharField(source="benefactor.slug")
    benefactor_logo_url = serializers.CharField(source="benefactor.logo_url")
    title = serializers.CharField()
    slug = serializers.CharField()
    short_code = serializers.CharField()
    description = serializers.CharField()
    suggested_amounts_rial = serializers.ListField(child=serializers.IntegerField())
    suggested_amounts_toman = serializers.SerializerMethodField()
    min_amount_rial = serializers.IntegerField()
    min_amount_toman = serializers.SerializerMethodField()
    max_amount_rial = serializers.IntegerField()
    max_amount_toman = serializers.SerializerMethodField()
    monthly_goal_rial = serializers.IntegerField()
    monthly_goal_toman = serializers.SerializerMethodField()
    total_raised_rial = serializers.IntegerField()
    total_raised_toman = serializers.SerializerMethodField()
    donor_count = serializers.IntegerField()
    is_active = serializers.BooleanField()

    def get_suggested_amounts_toman(self, obj: CharityJar) -> list[int]:
        """مبالغ پیشنهادی به تومان."""
        return [rial_to_toman(int(v)) for v in (obj.suggested_amounts_rial or [])]

    def get_min_amount_toman(self, obj: CharityJar) -> int:
        return rial_to_toman(obj.min_amount_rial)

    def get_max_amount_toman(self, obj: CharityJar) -> int:
        return rial_to_toman(obj.max_amount_rial)

    def get_monthly_goal_toman(self, obj: CharityJar) -> int:
        return rial_to_toman(obj.monthly_goal_rial)

    def get_total_raised_toman(self, obj: CharityJar) -> int:
        return rial_to_toman(obj.total_raised_rial)


class BenefactorPublicSerializer(serializers.Serializer[Any]):
    """نمای عمومی خیریه بدون افشای شماره شبا یا اطلاعات بانکی حساس."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    registration_number = serializers.CharField()
    province = serializers.CharField()
    city = serializers.CharField()
    short_bio = serializers.CharField()
    description = serializers.CharField()
    logo_url = serializers.CharField()
    cover_url = serializers.CharField()
    website_url = serializers.CharField()
    is_verified = serializers.BooleanField()
    active_campaigns_count = serializers.IntegerField()
    completed_campaigns_count = serializers.IntegerField()
    total_raised_rial = serializers.IntegerField()
    total_raised_toman = serializers.SerializerMethodField()
    total_disbursed_rial = serializers.IntegerField()
    total_disbursed_toman = serializers.SerializerMethodField()
    jars = serializers.SerializerMethodField()

    def get_total_raised_toman(self, obj: Benefactor) -> int:
        return rial_to_toman(obj.total_raised_rial)

    def get_total_disbursed_toman(self, obj: Benefactor) -> int:
        return rial_to_toman(obj.total_disbursed_rial)

    def get_jars(self, obj: Benefactor) -> list[dict[str, Any]]:
        if not is_feature_enabled("feature.charity_general_jars"):
            return []
        prefetched = getattr(obj, "prefetched_active_jars", None)
        jars = prefetched if prefetched is not None else obj.jars.filter(is_active=True)
        return list(CharityJarPublicSerializer(jars, many=True).data)


class BenefactorAdminSerializer(BenefactorPublicSerializer):
    """نمای مدیریتی خیریه شامل شماره شبا، شناسه ملی و وضعیت فعال بودن."""

    national_identifier = serializers.CharField()
    contact_phone = serializers.CharField()
    iban = serializers.CharField()
    bank_holder_name = serializers.CharField()
    is_active = serializers.BooleanField()
    display_order = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    created_at_jalali = serializers.SerializerMethodField()

    def get_created_at_jalali(self, obj: Benefactor) -> str | None:
        return format_jalali_datetime(obj.created_at)


class BenefactorWriteSerializer(serializers.Serializer[Any]):
    """ورودی ایجاد یا ویرایش خیریه توسط مدیر."""

    name = serializers.CharField(max_length=180)
    slug = serializers.CharField(max_length=120)
    registration_number = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default=""
    )
    national_identifier = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    province = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    short_bio = serializers.CharField(max_length=320, required=False, allow_blank=True, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="")
    logo_url = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    cover_url = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    website_url = serializers.CharField(
        max_length=300, required=False, allow_blank=True, default=""
    )
    contact_phone = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    iban = serializers.CharField(max_length=26, required=False, allow_blank=True, default="")
    bank_holder_name = serializers.CharField(
        max_length=180, required=False, allow_blank=True, default=""
    )
    is_verified = serializers.BooleanField(required=False, default=True)
    is_active = serializers.BooleanField(required=False, default=True)
    display_order = serializers.IntegerField(required=False, min_value=0, default=100)


class BenefactorPatchSerializer(BenefactorWriteSerializer):
    """ورودی ویرایش جزئی خیریه."""

    name = serializers.CharField(max_length=180, required=False)
    slug = serializers.CharField(max_length=120, required=False)


class CharityJarWriteSerializer(serializers.Serializer[Any]):
    """ورودی ایجاد قلک عام خیریه."""

    benefactor_id = serializers.UUIDField()
    title = serializers.CharField(max_length=180)
    slug = serializers.CharField(max_length=120)
    short_code = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="")
    suggested_amounts_rial = serializers.ListField(
        child=serializers.IntegerField(min_value=10_000),
        required=False,
    )
    min_amount_rial = serializers.IntegerField(min_value=10_000, required=False, default=100_000)
    max_amount_rial = serializers.IntegerField(
        min_value=10_000, required=False, default=5_000_000_000
    )
    monthly_goal_rial = serializers.IntegerField(min_value=0, required=False, default=0)
    is_active = serializers.BooleanField(required=False, default=True)


class CharityJarPatchSerializer(serializers.Serializer[Any]):
    """ورودی ویرایش جزئی قلک عام خیریه."""

    title = serializers.CharField(max_length=180, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    suggested_amounts_rial = serializers.ListField(
        child=serializers.IntegerField(min_value=10_000),
        required=False,
    )
    min_amount_rial = serializers.IntegerField(min_value=10_000, required=False)
    max_amount_rial = serializers.IntegerField(min_value=10_000, required=False)
    monthly_goal_rial = serializers.IntegerField(min_value=0, required=False)
    is_active = serializers.BooleanField(required=False)
