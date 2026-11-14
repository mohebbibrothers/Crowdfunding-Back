"""مدل‌های مشارکت، نیت خرید سریع ۳۰ ثانیه‌ای، پرداخت، نیت‌نامه، سفیر، رسید، اسنپ‌شات مرکل و ریسک."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.benefactors.models import Benefactor, CharityJar
from apps.campaigns.models import Campaign, MatchingGrant
from apps.contributions.choices import (
    ContributionStatus,
    ContributionTargetKind,
    DedicationType,
    GatewayName,
    InstallmentStatus,
    LateCaptureOutcome,
    PaymentRiskKind,
    PaymentStatus,
    PaymentTruthState,
    PledgeCancelReason,
    PledgeFrequency,
    PledgeStatus,
    RefundOutcome,
    SettlementRemediation,
    SettlementRowMatchStatus,
    SettlementSourceKind,
    SettlementStatementStatus,
)
from apps.core.models import BaseModel


class AmbassadorLink(BaseModel):
    """لینک سفیر اجتماعی برای دعوت خیرین به یک حرکت یا قلک با ثبت دقیق اثرگذاری (کلیک، نفر، سهم، ریال)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ambassador_links",
        verbose_name=_("کاربر سفیر"),
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="ambassador_links",
        verbose_name=_("حرکت هدف"),
    )
    charity_jar = models.ForeignKey(
        CharityJar,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="ambassador_links",
        verbose_name=_("قلک عام هدف"),
    )
    code = models.CharField(
        max_length=20, unique=True, db_index=True, verbose_name=_("کد یکتای سفیر")
    )
    custom_note = models.CharField(
        max_length=240, blank=True, default="", verbose_name=_("پیام دعوت سفیر")
    )
    click_count = models.PositiveIntegerField(default=0, verbose_name=_("تعداد کلیک"))
    referred_donors_count = models.PositiveIntegerField(
        default=0, verbose_name=_("تعداد مشارکت‌های موفق جذب‌شده")
    )
    attributed_shares = models.PositiveIntegerField(
        default=0, verbose_name=_("تعداد سهم جذب‌شده از طریق سفیر")
    )
    attributed_amount_rial = models.BigIntegerField(
        default=0, verbose_name=_("مجموع ریالی جذب‌شده از طریق سفیر")
    )
    is_active = models.BooleanField(default=True, verbose_name=_("فعال"))

    class Meta:
        verbose_name = _("لینک سفیر اجتماعی")
        verbose_name_plural = _("لینک‌های سفیران اجتماعی")
        ordering = ["-attributed_amount_rial", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (Q(campaign__isnull=False) & Q(charity_jar__isnull=True))
                    | (Q(campaign__isnull=True) & Q(charity_jar__isnull=False))
                ),
                name="ambassador_link_single_target_chk",
            ),
        ]

    def __str__(self) -> str:
        return f"Ambassador {self.code} ({self.attributed_amount_rial} IRR)"


class Contribution(BaseModel):
    """مشارکت خیر در خرید سهم یک حرکت یا واریز آزاد به قلک عام (با رزرو منصفانهٔ ۱۵ دقیقه‌ای)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="contributions",
        verbose_name=_("خیر مشارکت‌کننده"),
    )
    benefactor = models.ForeignKey(
        Benefactor,
        on_delete=models.PROTECT,
        related_name="contributions",
        verbose_name=_("خیریهٔ ذی‌نفع"),
    )
    target_kind = models.CharField(
        max_length=24,
        choices=ContributionTargetKind.choices,
        db_index=True,
        verbose_name=_("نوع مقصد مشارکت"),
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="contributions",
        verbose_name=_("حرکت"),
    )
    charity_jar = models.ForeignKey(
        CharityJar,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="contributions",
        verbose_name=_("قلک عام"),
    )
    ambassador_link = models.ForeignKey(
        AmbassadorLink,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contributions",
        verbose_name=_("لینک سفیر معرف"),
    )
    applied_matching_grant = models.ForeignKey(
        MatchingGrant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matched_contributions",
        verbose_name=_("حامی مضاعف‌کنندهٔ اعمال‌شده"),
    )

    shares_count = models.PositiveIntegerField(default=0, verbose_name=_("تعداد سهم خریداری‌شده"))
    matched_shares_awarded = models.PositiveIntegerField(
        default=0, verbose_name=_("تعداد سهم مضاعف‌شدهٔ حامی")
    )
    amount_rial = models.BigIntegerField(verbose_name=_("مبلغ پرداختی خیر (ریال)"))
    matched_amount_rial = models.BigIntegerField(
        default=0, verbose_name=_("مبلغ مضاعف‌شدهٔ حامی (ریال)")
    )

    is_anonymous = models.BooleanField(
        default=False,
        help_text=_("در صورت فعال بودن، نام خیر در فهرست عمومی به صورت «خیر گمنام» نمایش می‌یابد."),
        verbose_name=_("مشارکت ناشناس"),
    )
    public_note = models.CharField(
        max_length=200, blank=True, default="", verbose_name=_("دل‌نوشته / دعای خیر عمومی")
    )
    status = models.CharField(
        max_length=16,
        choices=ContributionStatus.choices,
        default=ContributionStatus.RESERVED,
        db_index=True,
        verbose_name=_("وضعیت مشارکت"),
    )
    hold_expires_at = models.DateTimeField(
        db_index=True, verbose_name=_("زمان انقضای رزرو ۱۵ دقیقه‌ای")
    )
    paid_at = models.DateTimeField(
        null=True, blank=True, db_index=True, verbose_name=_("زمان پرداخت")
    )
    refunded_at = models.DateTimeField(null=True, blank=True, verbose_name=_("زمان استرداد"))

    # ── پیوند به تعهد مستمر (اختیاری) ────────────────────────────────────────
    # هیچ منطق حسابداری تازه‌ای ساخته نمی‌شود: قسط ماهانه دقیقاً همان مسیر
    # مشارکت معمولی را طی می‌کند. این دو ستون فقط «منبع» را شفاف می‌کنند.
    pledge = models.ForeignKey(
        "RecurringPledge",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contributions",
        verbose_name=_("تعهد مستمر مبدأ"),
    )

    class Meta:
        verbose_name = _("مشارکت")
        verbose_name_plural = _("مشارکت‌ها")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "hold_expires_at"], name="contrib_status_hold_idx"),
            models.Index(fields=["campaign", "status", "-paid_at"], name="contrib_camp_paid_idx"),
            models.Index(fields=["user", "status", "-created_at"], name="contrib_user_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_rial__gte=10_000) & Q(matched_amount_rial__gte=0),
                name="contrib_positive_amount_chk",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        Q(target_kind=ContributionTargetKind.CAMPAIGN_SHARES)
                        & Q(campaign__isnull=False)
                        & Q(charity_jar__isnull=True)
                        & Q(shares_count__gte=1)
                    )
                    | (
                        Q(target_kind=ContributionTargetKind.CHARITY_JAR)
                        & Q(charity_jar__isnull=False)
                        & Q(campaign__isnull=True)
                        & Q(shares_count=0)
                    )
                ),
                name="contrib_target_consistency_chk",
            ),
        ]

    def __str__(self) -> str:
        return f"Contribution {self.id} [{self.status}] ({self.amount_rial} IRR)"


class ExpressContributionIntent(BaseModel):
    """نیت مشارکت سریع ۳۰ ثانیه‌ای مهمان (رزرو اطلاعات خرید + کد OTP هم‌زمان در یک گام)."""

    phone = models.CharField(max_length=11, db_index=True, verbose_name=_("شماره موبایل"))
    display_name = models.CharField(
        max_length=120, blank=True, default="", verbose_name=_("نام نمایشی اختیاری")
    )
    target_kind = models.CharField(
        max_length=24, choices=ContributionTargetKind.choices, verbose_name=_("نوع مقصد")
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="express_intents",
        verbose_name=_("حرکت"),
    )
    charity_jar = models.ForeignKey(
        CharityJar,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="express_intents",
        verbose_name=_("قلک عام"),
    )
    shares_count = models.PositiveIntegerField(default=0, verbose_name=_("تعداد سهم"))
    amount_rial = models.BigIntegerField(default=0, verbose_name=_("مبلغ ریالی (ویژه قلک)"))
    is_anonymous = models.BooleanField(default=False, verbose_name=_("مشارکت ناشناس"))
    public_note = models.CharField(
        max_length=200, blank=True, default="", verbose_name=_("دل‌نوشته")
    )
    ambassador_code = models.CharField(
        max_length=20, blank=True, default="", verbose_name=_("کد سفیر")
    )
    gateway_name = models.CharField(
        max_length=24, choices=GatewayName.choices, default=GatewayName.SANDBOX
    )
    dedication_payload = models.JSONField(
        default=dict, blank=True, verbose_name=_("اطلاعات نیت‌نامه اختیاری")
    )
    otp_challenge_id = models.UUIDField(verbose_name=_("شناسهٔ چالش OTP مرتبط"))
    expires_at = models.DateTimeField(db_index=True, verbose_name=_("زمان انقضا"))
    consumed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("زمان مصرف"))

    class Meta:
        verbose_name = _("نیت مشارکت سریع ۳۰ ثانیه‌ای")
        verbose_name_plural = _("نیت‌های مشارکت سریع ۳۰ ثانیه‌ای")
        ordering = ["-created_at"]


class Payment(BaseModel):
    """تراکنش درگاه پرداخت مرتبط با یک مشارکت."""

    contribution = models.ForeignKey(
        Contribution,
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name=_("مشارکت"),
    )
    gateway_name = models.CharField(
        max_length=24, choices=GatewayName.choices, db_index=True, verbose_name=_("درگاه پرداخت")
    )
    authority = models.CharField(
        max_length=80, unique=True, db_index=True, verbose_name=_("شناسهٔ Authority")
    )
    amount_rial = models.BigIntegerField(verbose_name=_("مبلغ تراکنش (ریال)"))
    redirect_url = models.CharField(max_length=500, verbose_name=_("نشانی هدایت به درگاه"))
    status = models.CharField(
        max_length=16,
        choices=PaymentStatus.choices,
        default=PaymentStatus.INITIATED,
        db_index=True,
        verbose_name=_("وضعیت تراکنش"),
    )
    ref_id = models.CharField(
        max_length=80, blank=True, default="", db_index=True, verbose_name=_("شماره پیگیری شاپرک")
    )
    card_pan_masked = models.CharField(
        max_length=32, blank=True, default="", verbose_name=_("شماره کارت پوشانده")
    )
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name=_("زمان تأیید درگاه"))

    # ── لایهٔ حقیقت وجه (Money Truth Layer) ────────────────────────────────────
    # این دو ستون عمداً از ``status`` جدا هستند:
    #   status      = «ما چه فکر می‌کنیم» (خودگواه)
    #   truth_state = «منبع مستقل چه می‌گوید» (صورتحساب بانک/درگاه)
    # تا وقتی این دو در یک ستون قاطی شوند، «تأییدشده» یعنی «خودمان گفتیم».
    truth_state = models.CharField(
        max_length=24,
        choices=PaymentTruthState.choices,
        default=PaymentTruthState.UNVERIFIED,
        db_index=True,
        verbose_name=_("وضعیت حقیقت وجه (منبع مستقل)"),
    )
    truth_confirmed_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("زمان تأیید مستقل توسط صورت‌حساب")
    )

    class Meta:
        verbose_name = _("پرداخت درگاه")
        verbose_name_plural = _("پرداخت‌های درگاه")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.gateway_name}:{self.authority} [{self.status}/{self.truth_state}]"


class PaymentEvent(BaseModel):
    """لاگ تغییرناپذیر رویدادهای ارسالی و دریافتی درگاه پرداخت."""

    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name="events",
        verbose_name=_("پرداخت"),
    )
    event_type = models.CharField(max_length=40, verbose_name=_("نوع رویداد"))
    raw_status = models.CharField(max_length=40, blank=True, default="", verbose_name=_("کد وضعیت"))
    details = models.JSONField(default=dict, blank=True, verbose_name=_("جزئیات"))

    class Meta:
        verbose_name = _("رویداد درگاه پرداخت")
        verbose_name_plural = _("رویدادهای درگاه پرداخت")
        ordering = ["created_at"]


class PaymentRefund(BaseModel):
    """ثبت استرداد وجه مشارکت تاییدشده به همراه سند معکوس دفترکل و آزادسازی سهم‌ها."""

    payment = models.OneToOneField(
        Payment,
        on_delete=models.PROTECT,
        related_name="refund",
        verbose_name=_("پرداخت مستردشده"),
    )
    amount_rial = models.BigIntegerField(verbose_name=_("مبلغ مستردشده (ریال)"))
    reason = models.CharField(max_length=400, verbose_name=_("علت استرداد"))
    bank_reference = models.CharField(
        max_length=80, blank=True, default="", verbose_name=_("مرجع بانکی استرداد")
    )
    refunded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="processed_refunds",
        verbose_name=_("کاربر ثبت‌کننده"),
    )

    outcome = models.CharField(
        max_length=16,
        choices=RefundOutcome.choices,
        default=RefundOutcome.COMPLETED,
        db_index=True,
        verbose_name=_("نتیجهٔ اجرای بازپرداخت"),
    )
    gateway_reference = models.CharField(
        max_length=80, blank=True, default="", verbose_name=_("مرجع بازپرداخت در درگاه")
    )
    gateway_raw_code = models.CharField(
        max_length=40, blank=True, default="", verbose_name=_("کد خام پاسخ درگاه")
    )
    attempt_count = models.PositiveSmallIntegerField(
        default=0, verbose_name=_("تعداد تلاش ارسال به درگاه")
    )
    last_attempt_at = models.DateTimeField(null=True, blank=True, verbose_name=_("زمان آخرین تلاش"))
    automation_note = models.CharField(
        max_length=400, blank=True, default="", verbose_name=_("توضیح مسیر خودکار")
    )

    class Meta:
        verbose_name = _("استرداد پرداخت")
        verbose_name_plural = _("استردادهای پرداخت")
        ordering = ["-created_at"]


class LateCaptureRecovery(BaseModel):
    """دفتر داوری «پرداختِ رهاشده» — قلب حلقهٔ نجات وجه.

    برای هر ``Payment`` که با وضعیت نامعلوم رها می‌شود دقیقاً **یک** رکورد ساخته
    می‌شود (یکتایی روی ``payment``) تا اجرای مکرر کرون هیچ‌گاه دو بار تخصیص
    یا دو بار بازپرداخت ایجاد نکند.

    این رکورد پاسخ سه پرسش را برای همیشه نگه می‌دارد:
      ۱) درگاه چه گفت؟        ⇒ ``gateway_verdict_raw``
      ۲) ما چه کردیم؟          ⇒ ``outcome``
      ۳) چرا؟                  ⇒ ``decision_reason``
    """

    payment = models.OneToOneField(
        Payment,
        on_delete=models.PROTECT,
        related_name="late_capture",
        verbose_name=_("پرداخت رهاشده"),
    )
    contribution = models.ForeignKey(
        Contribution,
        on_delete=models.PROTECT,
        related_name="late_captures",
        verbose_name=_("مشارکت مرتبط"),
    )

    outcome = models.CharField(
        max_length=20,
        choices=LateCaptureOutcome.choices,
        default=LateCaptureOutcome.MANUAL_REVIEW,
        db_index=True,
        verbose_name=_("داوری نهایی"),
    )
    decision_reason = models.CharField(
        max_length=200, blank=True, default="", verbose_name=_("دلیل تصمیم (ماشین‌خوان)")
    )
    gateway_verdict_raw = models.CharField(
        max_length=40, blank=True, default="", verbose_name=_("کد خام پاسخ درگاه")
    )
    gateway_ref_id = models.CharField(
        max_length=80, blank=True, default="", verbose_name=_("شماره پیگیری درگاه")
    )

    # وضعیت ظرفیت در لحظهٔ داوری، برای اینکه بعداً بتوان *چرا* را بازسازی کرد.
    capacity_at_decision = models.IntegerField(
        default=0, verbose_name=_("سهم آزاد حرکت در لحظهٔ داوری")
    )
    recovered_shares = models.PositiveIntegerField(
        default=0, verbose_name=_("سهم‌های تخصیص‌داده‌شده در مسیر نجات")
    )
    refund = models.ForeignKey(
        PaymentRefund,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="late_capture_recoveries",
        verbose_name=_("بازپرداخت صادرشده"),
    )

    resolved_at = models.DateTimeField(
        null=True, blank=True, db_index=True, verbose_name=_("زمان پایان تعیین تکلیف")
    )
    attempt_count = models.PositiveSmallIntegerField(
        default=0, verbose_name=_("تعداد تلاش استعلام از درگاه")
    )
    last_error = models.TextField(blank=True, default="", verbose_name=_("آخرین خطای داوری"))

    class Meta:
        verbose_name = _("بازیافت پرداخت رهاشده")
        verbose_name_plural = _("بازیافت‌های پرداخت رهاشده")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["outcome", "-created_at"], name="latecap_outcome_idx"),
        ]

    def __str__(self) -> str:
        return f"LateCapture {self.outcome} ({self.payment.authority})"

    @property
    def is_resolved(self) -> bool:
        """آیا این تراکنش رهاشده به تعیین تکلیف نهایی رسیده است؟"""
        return self.outcome != LateCaptureOutcome.MANUAL_REVIEW


class ExternalContribution(BaseModel):
    """مشارکت مستقیم خارج از درگاه آنلاین (فیش بانکی/تعهد خیریه) با ثبت در حساب انتظامی مجزا."""

    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.PROTECT,
        related_name="external_contributions",
        verbose_name=_("حرکت"),
    )
    shares_count = models.PositiveIntegerField(verbose_name=_("تعداد سهم معادل"))
    amount_rial = models.BigIntegerField(verbose_name=_("مبلغ معادل (ریال)"))
    donor_display_name = models.CharField(
        max_length=140, default="حامی مستقیم خیریه", verbose_name=_("عنوان نمایشی بانی")
    )
    reference_code = models.CharField(
        max_length=80, unique=True, verbose_name=_("شماره سند/فیش مرجع")
    )
    note = models.CharField(max_length=320, blank=True, default="", verbose_name=_("توضیحات"))
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_external_contributions",
        verbose_name=_("ثبت‌کننده"),
    )

    class Meta:
        verbose_name = _("مشارکت خارج از درگاه (آفلاین)")
        verbose_name_plural = _("مشارکت‌های خارج از درگاه (آفلاین)")
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(shares_count__gte=1) & Q(amount_rial__gt=0),
                name="external_contrib_positive_chk",
            ),
        ]


class DedicationCard(BaseModel):
    """گواهی نیت‌نامه و کارت هدیهٔ معنوی قابل اشتراک‌گذاری با لینک/QR امضاشده بدون افشای مبلغ ریالی."""

    contribution = models.OneToOneField(
        Contribution,
        on_delete=models.CASCADE,
        related_name="dedication_card",
        verbose_name=_("مشارکت"),
    )
    dedication_type = models.CharField(
        max_length=24,
        choices=DedicationType.choices,
        default=DedicationType.IN_MEMORY,
        verbose_name=_("نوع نیت‌نامه"),
    )
    honoree_name = models.CharField(max_length=140, verbose_name=_("به نام / به یادِ"))
    dedicator_display_name = models.CharField(
        max_length=140, blank=True, default="", verbose_name=_("از طرف (اختیاری)")
    )
    message = models.CharField(
        max_length=320, blank=True, default="", verbose_name=_("متن دل‌نوشته روی گواهی")
    )
    recipient_phone = models.CharField(
        max_length=11,
        blank=True,
        default="",
        help_text=_("در صورت وارد شدن، پس از پرداخت موفق لینک گواهی هدیه پیامک می‌شود."),
        verbose_name=_("موبایل گیرندهٔ هدیه"),
    )
    public_token = models.CharField(
        max_length=40, unique=True, db_index=True, verbose_name=_("توکن عمومی گواهی")
    )
    signature_hmac = models.CharField(max_length=64, verbose_name=_("امضای اصالت گواهی"))
    is_active = models.BooleanField(
        default=False,
        db_index=True,
        help_text=_("فقط پس از پرداخت قطعی مشارکت فعال می‌شود."),
        verbose_name=_("فعال برای نمایش عمومی"),
    )

    class Meta:
        verbose_name = _("گواهی نیت‌نامه و هدیه معنوی")
        verbose_name_plural = _("گواهی‌های نیت‌نامه و هدیه معنوی")
        ordering = ["-created_at"]


class DonationReceipt(BaseModel):
    """رسید رسمی قابل استعلام با امضای رمزنگاری HMAC-SHA256 برای هر مشارکت قطعی."""

    contribution = models.OneToOneField(
        Contribution,
        on_delete=models.PROTECT,
        related_name="receipt",
        verbose_name=_("مشارکت"),
    )
    receipt_number = models.CharField(
        max_length=40, unique=True, db_index=True, verbose_name=_("شماره سریال رسید")
    )
    verification_code = models.CharField(
        max_length=36, unique=True, db_index=True, verbose_name=_("کد رهگیری استعلام عمومی")
    )
    signature_hmac = models.CharField(max_length=64, verbose_name=_("امضای دیجیتال HMAC-SHA256"))

    class Meta:
        verbose_name = _("رسید مشارکت")
        verbose_name_plural = _("رسیدهای مشارکت")
        ordering = ["-created_at"]


class CampaignTransparencySnapshot(BaseModel):
    """اسنپ‌شات عمومی ریشهٔ درخت مرکل (Merkle Root) برای راستی‌آزمایی ریاضی مشارکت‌های یک حرکت."""

    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name="transparency_snapshots",
        verbose_name=_("حرکت"),
    )
    merkle_root = models.CharField(max_length=64, db_index=True, verbose_name=_("ریشهٔ درخت مرکل"))
    leaf_count = models.PositiveIntegerField(verbose_name=_("تعداد مشارکت‌های برگ"))
    online_shares_total = models.PositiveIntegerField(verbose_name=_("جمع سهم آنلاین در درخت"))
    matched_shares_total = models.PositiveIntegerField(verbose_name=_("جمع سهم مضاعف در درخت"))
    online_amount_rial = models.BigIntegerField(verbose_name=_("جمع ریالی آنلاین در درخت"))
    signature_hmac = models.CharField(max_length=64, verbose_name=_("امضای ریشه"))

    class Meta:
        verbose_name = _("اسنپ‌شات شفافیت مرکل حرکت")
        verbose_name_plural = _("اسنپ‌شات‌های شفافیت مرکل حرکت‌ها")
        ordering = ["-created_at"]


class PaymentRiskSignal(BaseModel):
    """سیگنال‌های ضدتقلب و جلوگیری از قفل‌کردن بدخواهانهٔ سهم‌های حرکت."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_risk_signals",
    )
    kind = models.CharField(max_length=40, choices=PaymentRiskKind.choices, db_index=True)
    ip_hash = models.CharField(max_length=64, blank=True, default="")
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("سیگنال ریسک پرداخت")
        verbose_name_plural = _("سیگنال‌های ریسک پرداخت")
        ordering = ["-created_at"]


# ══════════════════════════════════════════════════════════════════════════════
# لایهٔ حقیقت وجه (Money Truth Layer) — صورت‌حساب مستقل تسویهٔ درگاه
#
# چرا این مدل‌ها اینجا و نه در ``ledger``؟
#   • محور همه‌چیز ``Payment`` است که در همین اپ زندگی می‌کند.
#   • اگر ``SettlementRow`` در ``ledger`` باشد، برای ارجاع به ``Payment`` باید از
#     یک اپ بالاتر (contributions، رتبهٔ ۸) import کند — نقض صریح DAG.
#   • پس داده در ``contributions`` می‌ماند و موتور تطبیق هم همین‌جا زندگی می‌کند.
# ══════════════════════════════════════════════════════════════════════════════


class SettlementStatement(BaseModel):
    """یک سند صورت‌حساب تسویهٔ درگاه — «چشم مستقل» سامانه.

    این سند تنها منبعی در کل سامانه است که **خودش را تأیید نمی‌کند**: فایل از
    بانک/درگاه می‌آید، نه از ما. هر جا تناقضی بین ``Payment.status`` و این سند
    باشد، این سند برندهٔ بحث است، حتی اگر به ضرر ما باشد.

    قاعدهٔ یکتایی ``statement_sha256`` به‌ازای هر درگاه، عمدی است: ورود دوبارهٔ
    همان فایل باید همان سند را برگرداند، نه یک دستهٔ مغایرت دوم با نتایج متناقض.
    بدون این قید، بازپردازش یک بازه می‌توانست دو «حقیقت» موازی بسازد.
    """

    gateway_name = models.CharField(
        max_length=24, choices=GatewayName.choices, db_index=True, verbose_name=_("درگاه پرداخت")
    )
    source_kind = models.CharField(
        max_length=16,
        choices=SettlementSourceKind.choices,
        default=SettlementSourceKind.CSV,
        verbose_name=_("منبع ورود"),
    )
    statement_sha256 = models.CharField(
        max_length=64, db_index=True, verbose_name=_("اثر انگشت SHA-256 محتوای فایل")
    )
    original_filename = models.CharField(
        max_length=200, blank=True, default="", verbose_name=_("نام فایل مبدأ")
    )
    period_start = models.DateTimeField(verbose_name=_("شروع بازهٔ پوشش"))
    period_end = models.DateTimeField(verbose_name=_("پایان بازهٔ پوشش"))

    row_count = models.PositiveIntegerField(default=0, verbose_name=_("تعداد ردیف فایل"))
    declared_total_rial = models.BigIntegerField(
        default=0, verbose_name=_("جمع ریالی اعلامی خودِ فایل")
    )
    computed_total_rial = models.BigIntegerField(
        default=0, verbose_name=_("جمع ریالی محاسبه‌شده از ردیف‌ها")
    )
    integrity_ok = models.BooleanField(
        default=True,
        verbose_name=_("صحت داخلی سند (جمع اعلامی = جمع محاسبه‌شده)"),
    )
    integrity_note = models.CharField(
        max_length=300, blank=True, default="", verbose_name=_("توضیح نقض صحت")
    )

    status = models.CharField(
        max_length=16,
        choices=SettlementStatementStatus.choices,
        default=SettlementStatementStatus.INGESTED,
        db_index=True,
        verbose_name=_("وضعیت پردازش سند"),
    )
    ingested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ingested_settlements",
        verbose_name=_("کاربر وروددهنده"),
    )
    raw_document = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("فرادادهٔ خام سند"),
        help_text="فراداده و هدر فایل برای بازبینی آینده؛ ردیف‌ها در SettlementRow هستند.",
    )

    class Meta:
        verbose_name = _("سند صورت‌حساب تسویه")
        verbose_name_plural = _("اسناد صورت‌حساب تسویه")
        ordering = ["-period_end", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["gateway_name", "statement_sha256"],
                name="uniq_settlement_statement_per_gateway",
            )
        ]
        indexes = [
            models.Index(fields=["gateway_name", "period_end"], name="stmt_gw_period_idx"),
        ]

    def __str__(self) -> str:
        return (
            f"{self.gateway_name} statement [{self.period_start:%Y-%m-%d}.."
            f"{self.period_end:%Y-%m-%d}] rows={self.row_count}"
        )


class SettlementRow(BaseModel):
    """یک ردیف خام صورت‌حساب + نتیجهٔ تطبیق آن با دفتر داخلی.

    ``raw_payload`` عمداً نگه داشته می‌شود: فایل تسویهٔ فردا ستون تازه دارد. اگر
    فقط ستون‌های شناخته‌شده را ذخیره کنیم، بازپردازش گذشته غیرممکن می‌شود. با
    نگه‌داشتن ردیف خام، همیشه می‌توانیم گذشته را با منطق امروز دوباره بخوانیم.
    """

    statement = models.ForeignKey(
        SettlementStatement,
        on_delete=models.CASCADE,
        related_name="rows",
        verbose_name=_("سند صورت‌حساب"),
    )
    row_number = models.PositiveIntegerField(verbose_name=_("شمارهٔ سطر در فایل"))
    authority = models.CharField(
        max_length=80, blank=True, default="", db_index=True, verbose_name=_("شناسهٔ Authority")
    )
    ref_id = models.CharField(
        max_length=80, blank=True, default="", verbose_name=_("شمارهٔ پیگیری درگاه")
    )
    amount_rial = models.BigIntegerField(default=0, verbose_name=_("مبلغ ردیف (ریال)"))
    occurred_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("زمان تراکنش طبق فایل")
    )
    card_pan_masked = models.CharField(
        max_length=32, blank=True, default="", verbose_name=_("شماره کارت پوشانده")
    )
    description = models.CharField(
        max_length=300, blank=True, default="", verbose_name=_("توضیح ردیف فایل")
    )
    raw_payload = models.JSONField(
        default=dict, blank=True, verbose_name=_("ردیف خام فایل (برای بازپردازش آینده)")
    )

    match_status = models.CharField(
        max_length=24,
        choices=SettlementRowMatchStatus.choices,
        default=SettlementRowMatchStatus.PENDING,
        db_index=True,
        verbose_name=_("نتیجهٔ تطبیق"),
    )
    match_note = models.CharField(
        max_length=400, blank=True, default="", verbose_name=_("توضیح فارسی نتیجهٔ تطبیق")
    )
    payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="settlement_rows",
        verbose_name=_("پرداخت داخلی متناظر"),
    )
    remediation = models.CharField(
        max_length=20,
        choices=SettlementRemediation.choices,
        default=SettlementRemediation.NONE,
        db_index=True,
        verbose_name=_("اقدام انجام‌شده"),
    )
    remediation_note = models.CharField(
        max_length=400, blank=True, default="", verbose_name=_("توضیح اقدام")
    )
    remediated_at = models.DateTimeField(null=True, blank=True, verbose_name=_("زمان اقدام"))

    class Meta:
        verbose_name = _("ردیف صورت‌حساب تسویه")
        verbose_name_plural = _("ردیف‌های صورت‌حساب تسویه")
        ordering = ["statement", "row_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["statement", "row_number"], name="uniq_settlement_row_number"
            )
        ]
        indexes = [
            models.Index(fields=["statement", "match_status"], name="stmtrow_match_idx"),
        ]

    def __str__(self) -> str:
        return f"row#{self.row_number} {self.authority or '(no authority)'} [{self.match_status}]"


class SettlementReconciliation(BaseModel):
    """نتیجهٔ یک اجرای تطبیق روی یک سند صورت‌حساب — عکس فوری قابل ممیزی.

    چرا جدا از خود سند؟ چون یک سند می‌تواند چند بار تطبیق شود (پس از ورود
    ردیف‌های تازه یا اصلاح منطق). هر اجرا باید اثر انگشت خودش را برای ممیزی
    نگه دارد، وگرنه نمی‌توانیم بگوییم «این عدد را کی و با چه منطقی گفته‌ایم».
    """

    statement = models.ForeignKey(
        SettlementStatement,
        on_delete=models.CASCADE,
        related_name="reconciliations",
        verbose_name=_("سند صورت‌حساب"),
    )
    matched_count = models.PositiveIntegerField(default=0, verbose_name=_("تعداد منطبق"))
    amount_mismatch_count = models.PositiveIntegerField(
        default=0, verbose_name=_("تعداد مغایرت مبلغ")
    )
    missing_internal_count = models.PositiveIntegerField(
        default=0, verbose_name=_("تعداد پول بی‌مالک")
    )
    missing_gateway_count = models.PositiveIntegerField(
        default=0, verbose_name=_("تعداد پرداخت داخلی غایب در فایل")
    )
    internal_not_verified_count = models.PositiveIntegerField(
        default=0, verbose_name=_("تعداد پرداخت اثبات‌نشده که درگاه پول گرفت")
    )
    duplicate_in_file_count = models.PositiveIntegerField(
        default=0, verbose_name=_("تعداد Authority تکراری در فایل")
    )
    integrity_violations = models.PositiveIntegerField(
        default=0, verbose_name=_("تعداد ردیف‌های ردشده به‌دلیل نقص داده")
    )

    auto_healed_count = models.PositiveIntegerField(
        default=0, verbose_name=_("تعداد خوددرمانی موفق")
    )
    queued_review_count = models.PositiveIntegerField(
        default=0, verbose_name=_("تعداد ارجاع‌شده به بررسی انسانی")
    )
    financial_impact_rial = models.BigIntegerField(
        default=0,
        verbose_name=_("اثر ریالی خالص کشف‌شده"),
        help_text="مثبت = پول پیدا شد که در دفتر نبود؛ منفی = دفتری که پشتوانه ندارد.",
    )
    is_clean = models.BooleanField(default=False, verbose_name=_("بدون هیچ مغایرت باقی‌مانده"))
    dry_run = models.BooleanField(default=False, verbose_name=_("اجرای آزمایشی (بدون نوشتن)"))
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="settlement_reconciliations",
        verbose_name=_("کاربر اجراکننده"),
    )
    notes = models.JSONField(
        default=dict, blank=True, verbose_name=_("فرادادهٔ اجرا (سیاست‌های مؤثر، هشدارها)")
    )

    class Meta:
        verbose_name = _("نتیجهٔ تطبیق صورت‌حساب")
        verbose_name_plural = _("نتایج تطبیق صورت‌حساب‌ها")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        state = "پاک" if self.is_clean else "مغایرت‌دار"
        return f"reconciliation[{state}] impact={self.financial_impact_rial}"


# ══════════════════════════════════════════════════════════════════════════════
# تعهد کمک مستمر (Recurring Pledge)
#
# واقعیت درگاه‌های ایران: زرین‌پال و شاپرک «توکن کارت» و برداشت خودکار بدون
# حضور را نمی‌دهند. پس هر طراحی که فکر کند «مثل Stripe Subscription» است،
# در تولید شکست می‌خورد. مدل واقعی: تعهد + یادآوری + هدایت به همان درگاه.
# صداقت با خیر: نمی‌گوییم «خودکار»، می‌گوییم «ما یادت می‌اندازیم».
# ══════════════════════════════════════════════════════════════════════════════


class RecurringPledge(BaseModel):
    """تعهد کمک مستمر یک خیر به یک حرکت یا قلک.

    ``next_due_date`` عمداً ذخیره می‌شود و نه محاسبه: «ماه بعد» با ماه‌های
    ۲۸/۲۹/۳۰/۳۱ روزه به‌طور باورنکردنی باگ‌زا است. تصمیم یک بار گرفته
    می‌شود (روز ناموجود ⇒ آخرین روز ماه) و از آن به بعد فقط خوانده می‌شود.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recurring_pledges",
        verbose_name=_("خیر تعهددهنده"),
    )
    benefactor = models.ForeignKey(
        Benefactor,
        on_delete=models.PROTECT,
        related_name="recurring_pledges",
        verbose_name=_("خیریهٔ ذی‌نفع"),
    )
    target_kind = models.CharField(
        max_length=24,
        choices=ContributionTargetKind.choices,
        verbose_name=_("نوع مقصد قسط"),
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="recurring_pledges",
        verbose_name=_("حرکت"),
    )
    charity_jar = models.ForeignKey(
        CharityJar,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="recurring_pledges",
        verbose_name=_("قلک عام"),
    )

    amount_rial = models.BigIntegerField(verbose_name=_("مبلغ هر قسط (ریال)"))
    shares_count = models.PositiveIntegerField(
        default=0, verbose_name=_("تعداد سهم در هر قسط (در صورت حرکت سهم‌محور)")
    )
    frequency = models.CharField(
        max_length=16,
        choices=PledgeFrequency.choices,
        default=PledgeFrequency.MONTHLY,
        verbose_name=_("تناوب"),
    )
    interval_months = models.PositiveSmallIntegerField(
        default=1, verbose_name=_("فاصلهٔ ماهانه بین اقساط")
    )
    anchor_day = models.PositiveSmallIntegerField(
        help_text=_("روز ماه که قسط‌ها روی آن میخ می‌شوند (۱ تا ۳۱)."),
        verbose_name=_("روز مرجع در ماه"),
    )

    status = models.CharField(
        max_length=16,
        choices=PledgeStatus.choices,
        default=PledgeStatus.ACTIVE,
        db_index=True,
        verbose_name=_("وضعیت تعهد"),
    )
    next_due_date = models.DateField(db_index=True, verbose_name=_("تاریخ سررسید قسط بعدی"))
    pause_until = models.DateField(null=True, blank=True, verbose_name=_("توقف تا تاریخ"))

    total_paid_rial = models.BigIntegerField(default=0, verbose_name=_("جمع پرداختی (ریال)"))
    installments_paid = models.PositiveIntegerField(
        default=0, verbose_name=_("تعداد قسط پرداخت‌شده")
    )
    installments_skipped = models.PositiveIntegerField(default=0, verbose_name=_("تعداد قسط رد‌شده"))
    consecutive_failures = models.PositiveSmallIntegerField(
        default=0, verbose_name=_("شمار شکست‌های متوالی پرداخت")
    )
    last_paid_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("زمان آخرین قسط موفق")
    )

    cancel_reason = models.CharField(
        max_length=24,
        choices=PledgeCancelReason.choices,
        blank=True,
        default="",
        verbose_name=_("دلیل لغو/انقضا"),
    )
    cancelled_at = models.DateTimeField(null=True, blank=True, verbose_name=_("زمان لغو"))

    class Meta:
        verbose_name = _("تعهد کمک مستمر")
        verbose_name_plural = _("تعهدهای کمک مستمر")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "next_due_date"], name="pledge_status_due_idx"),
            models.Index(fields=["user", "status"], name="pledge_user_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(anchor_day__gte=1) & models.Q(anchor_day__lte=31),
                name="pledge_anchor_day_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_rial__gt=0), name="pledge_amount_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"pledge[{self.status}] {self.amount_rial:,} ریال · due {self.next_due_date}"

    @property
    def is_payable(self) -> bool:
        """آیا این تعهد می‌تواند قسط تازه تولید کند."""
        return self.status == PledgeStatus.ACTIVE


class PledgeInstallment(BaseModel):
    """یک قسط مشخص از یک تعهد — واحد دقیق «چیزی که باید پرداخت شود».

    قاعدهٔ آهنین: یکتایی روی ``(pledge, sequence)``. اجرای دوبارهٔ کرون
    **نمی‌تواند** دو قسط هم‌شماره بسازد. این تنها محافظ واقعی در برابر
    «دو بار کسر از حساب خیر» است — نه منطق برنامه، بلکه قید دیتابیس.
    """

    pledge = models.ForeignKey(
        RecurringPledge,
        on_delete=models.CASCADE,
        related_name="installments",
        verbose_name=_("تعهد"),
    )
    sequence = models.PositiveIntegerField(verbose_name=_("شمارهٔ ترتیبی قسط"))
    due_date = models.DateField(db_index=True, verbose_name=_("تاریخ سررسید"))
    grace_until = models.DateField(verbose_name=_("پایان مهلت پرداخت پس از سررسید"))
    amount_rial = models.BigIntegerField(
        help_text=_("عمداً جدا از تعهد: خیر می‌تواند مبلغ یک ماه را تغییر دهد."),
        verbose_name=_("مبلغ این قسط (ریال)"),
    )
    shares_count = models.PositiveIntegerField(default=0, verbose_name=_("تعداد سهم این قسط"))

    status = models.CharField(
        max_length=16,
        choices=InstallmentStatus.choices,
        default=InstallmentStatus.SCHEDULED,
        db_index=True,
        verbose_name=_("وضعیت قسط"),
    )
    reminded_at = models.DateTimeField(null=True, blank=True, verbose_name=_("زمان آخرین یادآوری"))
    reminder_count = models.PositiveSmallIntegerField(default=0, verbose_name=_("تعداد یادآوری"))

    contribution = models.ForeignKey(
        "Contribution",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pledge_installments",
        verbose_name=_("مشارکت پرداخت‌شدهٔ متناظر"),
    )
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name=_("زمان پرداخت"))
    failure_reason = models.CharField(
        max_length=200, blank=True, default="", verbose_name=_("دلیل پرداخت‌نشدن")
    )
    idempotency_key = models.CharField(
        max_length=120,
        help_text=_("کلید قطعی «pledge:{id}:seq:{n}» برای جلوگیری از کسر دوباره."),
        verbose_name=_("کلید هم‌توانی پرداخت"),
    )

    class Meta:
        verbose_name = _("قسط تعهد مستمر")
        verbose_name_plural = _("اقساط تعهد مستمر")
        ordering = ["pledge", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["pledge", "sequence"], name="uniq_installment_sequence_per_pledge"
            ),
        ]
        indexes = [
            models.Index(fields=["status", "due_date"], name="installment_status_due_idx"),
        ]

    def __str__(self) -> str:
        return f"installment#{self.sequence} of pledge {self.pledge_id} [{self.status}]"

    @property
    def is_open(self) -> bool:
        """آیا این قسط هنوز قابل پرداخت است."""
        return self.status in {
            InstallmentStatus.SCHEDULED,
            InstallmentStatus.REMINDED,
            InstallmentStatus.FAILED,
        }
