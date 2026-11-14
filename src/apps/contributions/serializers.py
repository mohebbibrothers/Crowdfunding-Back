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


# ══════════════════════════════════════════════════════════════════════════════
# قرارداد خروجی تایپشدهٔ نقاط پایانی شفافیت، رسید، نیتنامه و داشبورد خیر
# (پیشتر بهصورت {"type": "object"} بدون اسکیما به فرانتاند تحویل میشد)
# ══════════════════════════════════════════════════════════════════════════════


class SandboxPaymentOutputSerializer(serializers.Serializer[Any]):
    """اطلاعات تراکنش درگاه تعاملی Sandbox جهت رندر شبیهساز پرداخت."""

    authority = serializers.CharField()
    amount_rial = serializers.IntegerField()
    amount_toman = serializers.IntegerField()
    status = serializers.CharField()


class CampaignSupporterOutputSerializer(serializers.Serializer[Any]):
    """یک ردیف از دیوار عمومی همراهان حرکت (با احترام به گمنامی خیر)."""

    supporter_name = serializers.CharField()
    shares_count = serializers.IntegerField()
    matched_shares_awarded = serializers.IntegerField()
    public_note = serializers.CharField(allow_blank=True, allow_null=True)
    honoree_name = serializers.CharField(allow_blank=True, allow_null=True)
    paid_at = serializers.DateTimeField(allow_null=True)
    paid_at_jalali = serializers.CharField()


class MerkleAnchorOutputSerializer(serializers.Serializer[Any]):
    """لنگر امضاشدهٔ ریشهٔ درخت مرکل منتشرشده برای یک حرکت."""

    merkle_root = serializers.CharField()
    leaf_count = serializers.IntegerField()
    signature_hmac = serializers.CharField()
    captured_at = serializers.DateTimeField()
    captured_at_jalali = serializers.CharField()


class ExternalTransparencyItemSerializer(serializers.Serializer[Any]):
    """یک کمک ثبتشده خارج از درگاه در گزارش شفافیت عمومی."""

    donor_display_name = serializers.CharField()
    shares_count = serializers.IntegerField()
    amount_rial = serializers.IntegerField()
    amount_toman = serializers.IntegerField()
    reference_code = serializers.CharField()
    recorded_at_jalali = serializers.CharField()


class SharesBreakdownOutputSerializer(serializers.Serializer[Any]):
    """تفکیک سهام حرکت به آنلاین، مضاعفشده، آفلاین، رزروشده و باقیمانده."""

    total_shares = serializers.IntegerField()
    paid_online_shares = serializers.IntegerField()
    matched_sponsor_shares = serializers.IntegerField()
    external_offline_shares = serializers.IntegerField()
    reserved_shares = serializers.IntegerField()
    remaining_shares = serializers.IntegerField()


class AmountsBreakdownOutputSerializer(serializers.Serializer[Any]):
    """تفکیک مبالغ ریالی/تومانی هدف، جمعآوریشده، مضاعف، آفلاین و تسویهشده."""

    target_amount_rial = serializers.IntegerField()
    target_amount_toman = serializers.IntegerField()
    collected_online_rial = serializers.IntegerField()
    collected_online_toman = serializers.IntegerField()
    matched_amount_rial = serializers.IntegerField()
    matched_amount_toman = serializers.IntegerField()
    external_amount_rial = serializers.IntegerField()
    external_amount_toman = serializers.IntegerField()
    disbursed_to_benefactor_rial = serializers.IntegerField()
    disbursed_to_benefactor_toman = serializers.IntegerField()


class CampaignTransparencyOutputSerializer(serializers.Serializer[Any]):
    """گزارش کامل شفافیت مالی و رمزنگاری یک حرکت خیرخواهانه."""

    campaign_id = serializers.UUIDField()
    campaign_slug = serializers.CharField()
    campaign_title = serializers.CharField()
    benefactor_name = serializers.CharField()
    shares_breakdown = SharesBreakdownOutputSerializer()
    amounts_breakdown = AmountsBreakdownOutputSerializer()
    merkle_anchor = MerkleAnchorOutputSerializer(allow_null=True)
    external_contributions = ExternalTransparencyItemSerializer(many=True)


class MerkleProofVerifyOutputSerializer(serializers.Serializer[Any]):
    """نتیجهٔ راستیآزمایی ریاضی مستقل اثبات شمول مرکل."""

    valid = serializers.BooleanField()


class ReceiptVerificationOutputSerializer(serializers.Serializer[Any]):
    """استعلام عمومی اصالت رسید رسمی مشارکت (بدون افشای شماره موبایل خیر)."""

    valid = serializers.BooleanField()
    status = serializers.CharField()
    receipt_number = serializers.CharField()
    verification_code = serializers.CharField()
    signature_hmac = serializers.CharField()
    donor_display_name = serializers.CharField()
    benefactor_name = serializers.CharField()
    target_kind = serializers.CharField()
    target_title = serializers.CharField()
    shares_count = serializers.IntegerField()
    matched_shares_awarded = serializers.IntegerField()
    amount_rial = serializers.IntegerField()
    amount_toman = serializers.IntegerField()
    paid_at = serializers.DateTimeField(allow_null=True)
    paid_at_jalali = serializers.CharField()


class DedicationCertificateOutputSerializer(serializers.Serializer[Any]):
    """گواهی عمومی نیتنامه/کارت هدیهٔ معنوی (بدون نمایش هیچ مبلغ ریالی)."""

    public_token = serializers.CharField()
    dedication_type = serializers.CharField()
    honoree_name = serializers.CharField()
    dedicator_display_name = serializers.CharField()
    message = serializers.CharField(allow_blank=True)
    benefactor_name = serializers.CharField()
    benefactor_logo_url = serializers.CharField(allow_blank=True, allow_null=True)
    target_kind = serializers.CharField()
    target_title = serializers.CharField()
    target_slug = serializers.CharField(allow_blank=True)
    participation_badge = serializers.CharField()
    signature_hmac = serializers.CharField()
    issued_at = serializers.DateTimeField()
    issued_at_jalali = serializers.CharField()


class MerkleInclusionProofOutputSerializer(serializers.Serializer[Any]):
    """گواهی اثبات شمول یک مشارکت قطعی در درخت مرکل حرکت."""

    contribution_id = serializers.UUIDField()
    campaign_id = serializers.UUIDField()
    campaign_slug = serializers.CharField()
    leaf_index = serializers.IntegerField()
    total_leaves = serializers.IntegerField()
    leaf_hash = serializers.CharField()
    merkle_root = serializers.CharField()
    proof = serializers.ListField(child=serializers.DictField())
    verified = serializers.BooleanField()


class DashboardUserOutputSerializer(serializers.Serializer[Any]):
    """هویت نمایشی خیر در داشبورد انگیزشی."""

    id = serializers.UUIDField()
    display_name = serializers.CharField()
    phone = serializers.CharField()


class DashboardSummaryOutputSerializer(serializers.Serializer[Any]):
    """کارنامهٔ کمی خیر (همهٔ مبالغ جفت ریال/تومان دارند)."""

    total_contributions_count = serializers.IntegerField()
    campaign_shares_bought = serializers.IntegerField()
    matched_shares_unlocked = serializers.IntegerField()
    total_effective_shares = serializers.IntegerField()
    charity_jar_donations_count = serializers.IntegerField()
    charity_jar_total_rial = serializers.IntegerField()
    charity_jar_total_toman = serializers.IntegerField()
    total_contributed_rial = serializers.IntegerField()
    total_contributed_toman = serializers.IntegerField()
    total_impact_with_matching_rial = serializers.IntegerField()
    total_impact_with_matching_toman = serializers.IntegerField()
    backed_campaigns_count = serializers.IntegerField()
    completed_backed_campaigns_count = serializers.IntegerField()
    benefactors_supported_count = serializers.IntegerField()
    active_dedications_count = serializers.IntegerField()
    unread_notifications_count = serializers.IntegerField()


class AmbassadorImpactLinkOutputSerializer(serializers.Serializer[Any]):
    """خلاصهٔ اثر یک لینک سفیر اجتماعی."""

    code = serializers.CharField()
    target_title = serializers.CharField(allow_blank=True)
    click_count = serializers.IntegerField()
    referred_donors_count = serializers.IntegerField()
    attributed_shares = serializers.IntegerField()
    attributed_amount_rial = serializers.IntegerField()
    attributed_amount_toman = serializers.IntegerField()


class DashboardAmbassadorImpactOutputSerializer(serializers.Serializer[Any]):
    """کارنامهٔ کلی سفیر اجتماعی خیر."""

    links_count = serializers.IntegerField()
    total_clicks = serializers.IntegerField()
    referred_donors_count = serializers.IntegerField()
    attributed_shares = serializers.IntegerField()
    attributed_amount_rial = serializers.IntegerField()
    attributed_amount_toman = serializers.IntegerField()
    links = AmbassadorImpactLinkOutputSerializer(many=True)


class MotivationBadgeOutputSerializer(serializers.Serializer[Any]):
    """یک نشان افتخار (قفل/باز) در کارنامهٔ معنوی خیر."""

    code = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    earned = serializers.BooleanField()
    current = serializers.IntegerField()
    target = serializers.IntegerField()


class DashboardMotivationOutputSerializer(serializers.Serializer[Any]):
    """انگیزهبخشی: استمرار ماهانه و نشانهای افتخار."""

    active_months_streak = serializers.IntegerField()
    earned_badges_count = serializers.IntegerField()
    total_badges_count = serializers.IntegerField()
    badges = MotivationBadgeOutputSerializer(many=True)


class DonorDashboardOutputSerializer(serializers.Serializer[Any]):
    """داشبورد جامع خیر: کارنامه، سفیر، انگیزه، رزروها، تایملاین و پیشنهادها."""

    user = DashboardUserOutputSerializer()
    summary = DashboardSummaryOutputSerializer()
    ambassador_impact = DashboardAmbassadorImpactOutputSerializer()
    motivation = DashboardMotivationOutputSerializer()
    active_reservations = serializers.ListField(child=serializers.DictField())
    backed_campaigns = serializers.ListField(child=serializers.DictField())
    backed_impact_timeline = serializers.ListField(child=serializers.DictField())
    recent_contributions = serializers.ListField(child=serializers.DictField())
    recommended_campaigns = serializers.ListField(child=serializers.DictField())


class RefundResultOutputSerializer(serializers.Serializer[Any]):
    """نتیجهٔ استرداد وجه همراه با سند معکوس دفترکل."""

    refund_id = serializers.UUIDField()
    amount_rial = serializers.IntegerField()
    status = serializers.CharField()


# ══════════════════════════════════════════════════════════════════════════════
# تعهد کمک مستمر (v1.4.0)
#
# طراحی خروجی‌ها با یک قاعده: عدد ریالی **همیشه** هم به ریال و هم به تومان
# برگردد. خیر ایرانی به تومان فکر می‌کند، دفتر کل به ریال. تبدیل در نمایش،
# نه در پایگاه داده — همان قاعده‌ای که از v1.1.0 رعایت شده است.
# ══════════════════════════════════════════════════════════════════════════════


class PledgeCreateInputSerializer(serializers.Serializer[Any]):
    """ورودی ساخت تعهد کمک مستمر."""

    target_kind = serializers.ChoiceField(choices=ContributionTargetKind.choices)
    campaign_id = serializers.UUIDField(required=False, allow_null=True)
    charity_jar_id = serializers.UUIDField(required=False, allow_null=True)
    amount_rial = serializers.IntegerField(min_value=1)
    frequency = serializers.ChoiceField(
        choices=[("monthly", "ماهانه"), ("quarterly", "سه‌ماهه")], default="monthly"
    )
    shares_count = serializers.IntegerField(min_value=0, default=0)
    start_day = serializers.IntegerField(min_value=1, max_value=31, required=False, allow_null=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """اعتبارسنجی متقابل: مقصد باید با نوع هم‌خوان باشد و دقیقاً یکی باشد."""
        kind = attrs.get("target_kind")
        has_campaign = attrs.get("campaign_id") is not None
        has_jar = attrs.get("charity_jar_id") is not None
        if kind == ContributionTargetKind.CAMPAIGN_SHARES and not has_campaign:
            raise serializers.ValidationError(
                {"campaign_id": "برای تعهد سهم‌محور، شناسهٔ حرکت الزامی است."}
            )
        if kind == ContributionTargetKind.CHARITY_JAR and not has_jar:
            raise serializers.ValidationError(
                {"charity_jar_id": "برای تعهد قلک، شناسهٔ قلک الزامی است."}
            )
        if has_campaign and has_jar:
            raise serializers.ValidationError(
                {"non_field_errors": "فقط یکی از حرکت یا قلک را انتخاب کنید، نه هر دو."}
            )
        return attrs


class PledgeUpdateInputSerializer(serializers.Serializer[Any]):
    """ورودی ویرایش تعهد: مبلغ، تناوب، روز شروع یا توقف موقت."""

    amount_rial = serializers.IntegerField(min_value=1, required=False)
    frequency = serializers.ChoiceField(
        choices=[("monthly", "ماهانه"), ("quarterly", "سه‌ماهه")], required=False
    )
    start_day = serializers.IntegerField(min_value=1, max_value=31, required=False)
    pause_until = serializers.DateField(required=False, allow_null=True)


class PledgeInstallmentOutputSerializer(serializers.Serializer[Any]):
    """یک قسط تعهد مستمر — با وضعیت خوانا و مبلغ به تومان."""

    id = serializers.UUIDField()
    sequence = serializers.IntegerField()
    due_date = serializers.DateField()
    grace_until = serializers.DateField()
    amount_rial = serializers.IntegerField()
    amount_toman = serializers.IntegerField()
    status = serializers.CharField()
    status_display = serializers.CharField()
    is_open = serializers.BooleanField()
    reminder_count = serializers.IntegerField()
    failure_reason = serializers.CharField(allow_blank=True)
    can_pay = serializers.BooleanField()
    can_skip = serializers.BooleanField()
    contribution_id = serializers.UUIDField(allow_null=True)


class PledgeOutputSerializer(serializers.Serializer[Any]):
    """تعهد مستمر با خلاصهٔ اقساط و وضعیت قابل‌اقدام."""

    id = serializers.UUIDField()
    status = serializers.CharField()
    status_display = serializers.CharField()
    target_kind = serializers.CharField()
    target_title = serializers.CharField(allow_blank=True)
    amount_rial = serializers.IntegerField()
    amount_toman = serializers.IntegerField()
    frequency = serializers.CharField()
    frequency_display = serializers.CharField()
    interval_months = serializers.IntegerField()
    anchor_day = serializers.IntegerField()
    next_due_date = serializers.DateField()
    total_paid_rial = serializers.IntegerField()
    total_paid_toman = serializers.IntegerField()
    installments_paid = serializers.IntegerField()
    installments_skipped = serializers.IntegerField()
    consecutive_failures = serializers.IntegerField()
    pause_until = serializers.DateField(allow_null=True)
    created_at = serializers.DateTimeField()
    open_installments = serializers.IntegerField()
    next_payable_installment_id = serializers.UUIDField(allow_null=True)


class PledgePayInputSerializer(serializers.Serializer[Any]):
    """ورودی آغاز پرداخت یک قسط."""

    installment_id = serializers.UUIDField()
    gateway_name = serializers.CharField(required=False, allow_blank=True, default="")


class PledgePayOutputSerializer(serializers.Serializer[Any]):
    """نتیجهٔ آغاز پرداخت قسط: شناسهٔ پرداخت و لینک درگاه."""

    installment_id = serializers.UUIDField()
    contribution_id = serializers.UUIDField()
    payment_id = serializers.UUIDField()
    amount_rial = serializers.IntegerField()
    amount_toman = serializers.IntegerField()
    redirect_url = serializers.CharField(allow_blank=True)


class PledgeCancelInputSerializer(serializers.Serializer[Any]):
    """ورودی لغو یا رد قسط."""

    reason = serializers.CharField(required=False, allow_blank=True, default="user_request")


class AdminPledgeSerializer(serializers.Serializer[Any]):
    """ردیف تعهد در پنل مدیریت — با هویت خیر (ماسک‌شدهٔ امن)."""

    id = serializers.UUIDField()
    user_id = serializers.UUIDField()
    user_phone_masked = serializers.CharField()
    status = serializers.CharField()
    target_kind = serializers.CharField()
    target_title = serializers.CharField(allow_blank=True)
    amount_rial = serializers.IntegerField()
    amount_toman = serializers.IntegerField()
    frequency = serializers.CharField()
    next_due_date = serializers.DateField()
    total_paid_rial = serializers.IntegerField()
    installments_paid = serializers.IntegerField()
    consecutive_failures = serializers.IntegerField()
    created_at = serializers.DateTimeField()


class PledgeStatsOutputSerializer(serializers.Serializer[Any]):
    """آمار تجمیعی تعهدهای مستمر — مبنای بودجه‌بندی خیریه."""

    active_pledges = serializers.IntegerField()
    paused_pledges = serializers.IntegerField()
    expired_pledges = serializers.IntegerField()
    cancelled_pledges = serializers.IntegerField()
    monthly_recurring_revenue_rial = serializers.IntegerField()
    monthly_recurring_revenue_toman = serializers.IntegerField()
    active_pledge_amount_rial = serializers.IntegerField()
    collection_rate = serializers.FloatField()
    paid_installments_window = serializers.IntegerField()
    failed_installments_window = serializers.IntegerField()
    churn_window = serializers.IntegerField()
    churn_rate = serializers.FloatField()
    average_pledge_lifetime_months = serializers.FloatField()
    top_failure_reasons = serializers.ListField(child=serializers.DictField())
    generated_for_window_days = serializers.IntegerField()


class PledgeCycleOutputSerializer(serializers.Serializer[Any]):
    """نتیجهٔ یک اجرای دستی چرخهٔ تعهد مستمر."""

    materialize = serializers.DictField()
    reminders = serializers.DictField()
    expiry = serializers.DictField()
    resumed = serializers.IntegerField()
