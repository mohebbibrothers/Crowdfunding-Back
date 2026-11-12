"""سریالایزرهای مشارکت، خرید سریع ۳۰ ثانیه‌ای، پرداخت، نیت‌نامه، سفیران، مرکل و داشبورد خیر."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.contributions.choices import (
    ContributionTargetKind,
    DedicationType,
    GatewayName,
)
from apps.contributions.models import AmbassadorLink, Contribution, ExternalContribution, Payment
from apps.core.crypto import mask_phone
from apps.core.jalali import format_jalali_datetime
from apps.core.money import rial_to_toman


class DedicationInputSerializer(serializers.Serializer[Any]):
    """ورودی اختیاری نیت‌نامه هنگام ثبت مشارکت."""

    dedication_type = serializers.ChoiceField(
        choices=DedicationType.choices, default=DedicationType.IN_MEMORY
    )
    honoree_name = serializers.CharField(max_length=140)
    dedicator_display_name = serializers.CharField(
        max_length=140, required=False, allow_blank=True, default=""
    )
    message = serializers.CharField(max_length=320, required=False, allow_blank=True, default="")
    recipient_phone = serializers.CharField(
        max_length=16, required=False, allow_blank=True, default=""
    )


class CheckoutInitiateInputSerializer(serializers.Serializer[Any]):
    """ورودی آغاز مشارکت و رزرو ۱۵ دقیقه‌ای سهم (یا واریز قلک عام) برای کاربر احراز هویت‌شده."""

    target_kind = serializers.ChoiceField(
        choices=ContributionTargetKind.choices,
        default=ContributionTargetKind.CAMPAIGN_SHARES,
    )
    campaign_id = serializers.UUIDField(required=False, allow_null=True)
    charity_jar_id = serializers.UUIDField(required=False, allow_null=True)
    shares_count = serializers.IntegerField(min_value=0, required=False, default=1)
    amount_rial = serializers.IntegerField(min_value=0, required=False, default=0)
    is_anonymous = serializers.BooleanField(required=False, default=False)
    public_note = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )
    ambassador_code = serializers.CharField(
        max_length=20, required=False, allow_blank=True, default=""
    )
    gateway_name = serializers.ChoiceField(
        choices=GatewayName.choices, required=False, default=GatewayName.SANDBOX
    )
    dedication = DedicationInputSerializer(required=False)


class CheckoutInitiateResponseSerializer(serializers.Serializer[Any]):
    """پاسخ ایجاد مشارکت و لینک هدایت به درگاه پرداخت."""

    contribution_id = serializers.UUIDField()
    payment_id = serializers.UUIDField()
    authority = serializers.CharField()
    gateway_name = serializers.CharField()
    gateway_redirect_url = serializers.CharField()
    shares_count = serializers.IntegerField()
    amount_rial = serializers.IntegerField()
    amount_toman = serializers.IntegerField()
    hold_expires_at = serializers.DateTimeField()


class ExpressStartInputSerializer(CheckoutInitiateInputSerializer):
    """ورودی گام اول مشارکت سریع ۳۰ ثانیه‌ای مهمان (همراه با شماره موبایل)."""

    phone = serializers.CharField(max_length=16)
    display_name = serializers.CharField(
        max_length=120, required=False, allow_blank=True, default=""
    )


class ExpressStartResponseSerializer(serializers.Serializer[Any]):
    """پاسخ گام اول مشارکت سریع مهمان."""

    intent_id = serializers.UUIDField()
    expires_in = serializers.IntegerField()
    amount_rial = serializers.IntegerField()
    amount_toman = serializers.SerializerMethodField()
    shares_count = serializers.IntegerField()
    dev_code = serializers.CharField(required=False)

    def get_amount_toman(self, obj: dict[str, Any]) -> int:
        return rial_to_toman(int(obj["amount_rial"]))


class ExpressConfirmInputSerializer(serializers.Serializer[Any]):
    """ورودی گام دوم مشارکت سریع ۳۰ ثانیه‌ای مهمان (کد ۵ رقمی OTP)."""

    intent_id = serializers.UUIDField()
    code = serializers.RegexField(regex=r"^\d{5}$")


class PaymentCallbackVerifyInputSerializer(serializers.Serializer[Any]):
    """ورودی تأیید بازگشت از درگاه پرداخت."""

    authority = serializers.CharField(max_length=80)
    status = serializers.CharField(max_length=24, default="OK")


class PaymentVerifyResponseSerializer(serializers.Serializer[Any]):
    """پاسخ تأیید تراکنش درگاه پرداخت."""

    verified = serializers.BooleanField()
    payment_status = serializers.CharField()
    contribution_id = serializers.UUIDField()
    ref_id = serializers.CharField()
    shares_count = serializers.IntegerField()
    matched_shares_awarded = serializers.IntegerField()
    amount_rial = serializers.IntegerField()
    amount_toman = serializers.IntegerField()
    receipt_number = serializers.CharField(allow_null=True)
    verification_code = serializers.CharField(allow_null=True)
    dedication_token = serializers.CharField(allow_null=True)


class ContributionUserSerializer(serializers.Serializer[Any]):
    """نمای مشارکت در فهرست تاریخچهٔ کاربر."""

    id = serializers.UUIDField()
    target_kind = serializers.CharField()
    target_title = serializers.SerializerMethodField()
    benefactor_name = serializers.CharField(source="benefactor.name")
    shares_count = serializers.IntegerField()
    matched_shares_awarded = serializers.IntegerField()
    amount_rial = serializers.IntegerField()
    amount_toman = serializers.SerializerMethodField()
    is_anonymous = serializers.BooleanField()
    status = serializers.CharField()
    hold_expires_at = serializers.DateTimeField()
    paid_at = serializers.DateTimeField(allow_null=True)
    paid_at_jalali = serializers.SerializerMethodField()
    receipt_verification_code = serializers.SerializerMethodField()
    dedication_token = serializers.SerializerMethodField()

    def get_target_title(self, obj: Contribution) -> str:
        if obj.campaign is not None:
            return obj.campaign.title
        if obj.charity_jar is not None:
            return obj.charity_jar.title
        return obj.benefactor.name

    def get_amount_toman(self, obj: Contribution) -> int:
        return rial_to_toman(obj.amount_rial)

    def get_paid_at_jalali(self, obj: Contribution) -> str | None:
        return format_jalali_datetime(obj.paid_at)

    def get_receipt_verification_code(self, obj: Contribution) -> str | None:
        r = getattr(obj, "receipt", None)
        return r.verification_code if r else None

    def get_dedication_token(self, obj: Contribution) -> str | None:
        d = getattr(obj, "dedication_card", None)
        return d.public_token if (d and d.is_active) else None


class AmbassadorCreateInputSerializer(serializers.Serializer[Any]):
    """ورودی ساخت لینک سفیر اجتماعی برای حرکت یا قلک."""

    campaign_id = serializers.UUIDField(required=False, allow_null=True)
    charity_jar_id = serializers.UUIDField(required=False, allow_null=True)
    custom_note = serializers.CharField(
        max_length=240, required=False, allow_blank=True, default=""
    )


class AmbassadorLinkSerializer(serializers.Serializer[Any]):
    """نمای خروجی لینک سفیر اجتماعی."""

    id = serializers.UUIDField()
    code = serializers.CharField()
    campaign_id = serializers.UUIDField(allow_null=True)
    charity_jar_id = serializers.UUIDField(allow_null=True)
    target_title = serializers.SerializerMethodField()
    custom_note = serializers.CharField()
    click_count = serializers.IntegerField()
    referred_donors_count = serializers.IntegerField()
    attributed_shares = serializers.IntegerField()
    attributed_amount_rial = serializers.IntegerField()
    attributed_amount_toman = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField()

    def get_target_title(self, obj: AmbassadorLink) -> str:
        if obj.campaign is not None:
            return obj.campaign.title
        if obj.charity_jar is not None:
            return obj.charity_jar.title
        return ""

    def get_attributed_amount_toman(self, obj: AmbassadorLink) -> int:
        return rial_to_toman(obj.attributed_amount_rial)


class MerkleProofVerifyInputSerializer(serializers.Serializer[Any]):
    """ورودی راستی‌آزمایی مستقل اثبات شمول درخت مرکل."""

    leaf_hash = serializers.CharField(min_length=64, max_length=64)
    merkle_root = serializers.CharField(min_length=64, max_length=64)
    proof = serializers.ListField(child=serializers.DictField())


class ExternalContributionWriteSerializer(serializers.Serializer[Any]):
    """ورودی ثبت مشارکت خارج از درگاه آنلاین توسط مدیر."""

    shares_count = serializers.IntegerField(min_value=1)
    donor_display_name = serializers.CharField(
        max_length=140, required=False, default="حامی مستقیم خیریه"
    )
    reference_code = serializers.CharField(max_length=80)
    note = serializers.CharField(max_length=320, required=False, allow_blank=True, default="")


class ExternalContributionSerializer(serializers.Serializer[Any]):
    """نمای خروجی مشارکت خارج از درگاه."""

    id = serializers.UUIDField()
    campaign_id = serializers.UUIDField()
    shares_count = serializers.IntegerField()
    amount_rial = serializers.IntegerField()
    amount_toman = serializers.SerializerMethodField()
    donor_display_name = serializers.CharField()
    reference_code = serializers.CharField()
    note = serializers.CharField()
    created_at = serializers.DateTimeField()

    def get_amount_toman(self, obj: ExternalContribution) -> int:
        return rial_to_toman(obj.amount_rial)


class PaymentRefundInputSerializer(serializers.Serializer[Any]):
    """ورودی استرداد پرداخت تاییدشده توسط مدیر مالی (Step-Up MFA)."""

    reason = serializers.CharField(min_length=3, max_length=400)
    bank_reference = serializers.CharField(
        max_length=80, required=False, allow_blank=True, default=""
    )


class AdminPaymentSerializer(serializers.Serializer[Any]):
    """نمای مدیریتی پرداخت با پوشاندن شماره موبایل خیر به صورت پیش‌فرض."""

    id = serializers.UUIDField()
    contribution_id = serializers.UUIDField()
    gateway_name = serializers.CharField()
    authority = serializers.CharField()
    ref_id = serializers.CharField()
    status = serializers.CharField()
    amount_rial = serializers.IntegerField()
    amount_toman = serializers.SerializerMethodField()
    donor_phone_masked = serializers.SerializerMethodField()
    donor_user_id = serializers.UUIDField(source="contribution.user_id")
    benefactor_name = serializers.CharField(source="contribution.benefactor.name")
    target_title = serializers.SerializerMethodField()
    verified_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()

    def get_amount_toman(self, obj: Payment) -> int:
        return rial_to_toman(obj.amount_rial)

    def get_donor_phone_masked(self, obj: Payment) -> str:
        return mask_phone(obj.contribution.user.phone)

    def get_target_title(self, obj: Payment) -> str:
        c = obj.contribution
        if c.campaign is not None:
            return c.campaign.title
        if c.charity_jar is not None:
            return c.charity_jar.title
        return c.benefactor.name
