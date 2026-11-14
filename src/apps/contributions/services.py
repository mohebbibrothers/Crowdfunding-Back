"""سرویس‌های تراکنشی مشارکت‌ها: رزرو ۱۵ دقیقه‌ای، خرید سریع ۳۰ ثانیه‌ای، تسویه درگاه، مرکل، سفیر و استرداد."""

from __future__ import annotations

from datetime import timedelta
import hashlib
import hmac
import logging
import secrets
import string
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.audit.choices import AuditAction
from apps.audit.services import record_audit_event
from apps.benefactors.models import Benefactor, CharityJar
from apps.campaigns.choices import CampaignStatus
from apps.campaigns.models import Campaign, MatchingGrant
from apps.campaigns.services import sync_benefactor_campaign_counters
from apps.contributions.choices import (
    ContributionStatus,
    ContributionTargetKind,
    GatewayName,
    LateCaptureOutcome,
    PaymentRiskKind,
    PaymentStatus,
    RefundOutcome,
)
from apps.contributions.gateways import resolve_payment_gateway
from apps.contributions.merkle import (
    MerkleLeafInput,
    build_merkle_levels,
    compute_leaf_hash,
    generate_inclusion_proof,
    verify_inclusion_proof,
)
from apps.contributions.models import (
    AmbassadorLink,
    CampaignTransparencySnapshot,
    Contribution,
    DedicationCard,
    DonationReceipt,
    ExpressContributionIntent,
    ExternalContribution,
    LateCaptureRecovery,
    Payment,
    PaymentEvent,
    PaymentRefund,
    PaymentRiskSignal,
    PledgeInstallment,
)
from apps.contributions.recurring import settle_installment_payment
from apps.core.cache import bump_epoch
from apps.core.crypto import blind_index
from apps.core.db.serial import serialize_on
from apps.core.errors import (
    ConflictError,
    FeatureDisabledError,
    NotFoundError,
    RateLimitedError,
    ValidationError as DomainValidationError,
)
from apps.core.metrics import LATE_CAPTURE_RECOVERIES_TOTAL, REFUND_DISPATCH_TOTAL
from apps.core.middleware import client_ip
from apps.core.models import OutboxMessage
from apps.core.outbox import enqueue_outbox, register_outbox_handler
from apps.core.policy import get_policy, is_feature_enabled
from apps.identity.choices import OtpPurpose
from apps.identity.models import User
from apps.identity.services import (
    OTP_TTL_SECONDS,
    IssuedAuthTokens,
    establish_dual_session,
    request_otp,
    verify_otp_and_get_user,
)
from apps.identity.validators import normalize_phone
from apps.ledger.choices import JournalEntryKind, LedgerAccountType
from apps.ledger.services import (
    ACC_EXTERNAL_CUSTODY,
    ACC_GATEWAY_RECEIVABLE,
    ACC_MATCHING_POOL,
    PostingLineSpec,
    benefactor_external_equity_spec,
    benefactor_online_payable_spec,
    post_journal_entry,
)
from apps.notifications.choices import UserNotificationKind
from apps.notifications.services import create_user_notification

logger = logging.getLogger(__name__)

_CODE_ALPHABET = string.ascii_lowercase + string.digits

# حساب بدهی «وجه دریافتی که باید به حامی بازگردد». تعهدی که نمی‌توان آن را نادیده گرفت؛
# تا زمانی که بازپرداخت به پایان نرسد، این حساب صفر نمی‌شود و در ترازنامه دیده می‌شود.
ACC_REFUND_LIABILITY = "SYS:LIAB:REFUND_PAYABLE"


def _sign_artifact(domain_tag: str, canonical_payload: str) -> str:
    """امضای HMAC-SHA256 برای رسیدها، نیت‌نامه‌ها و ریشه‌های درخت مرکل."""
    key = str(getattr(settings, "AUDIT_ANCHOR_HMAC_KEY", settings.SECRET_KEY)).encode("utf-8")
    msg = f"{domain_tag}|{canonical_payload}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


@transaction.atomic
@transaction.atomic
def release_expired_share_holds(*, campaign_id: Any = None) -> int:
    """آزادسازی اتمیک رزروهای ۱۵ دقیقه‌ای منقضی‌شده و بازگرداندن سهم‌ها به ظرفیت آزاد حرکت.

    ⚠️ تفکیک حیاتی نسبت به نسخهٔ پیشین:
        پیش‌تر پرداخت‌های ``INITIATED`` کورکورانه ``FAILED`` می‌شدند. اما
        «رزرو منقضی شد» هرگز به معنای «پولی گرفته نشد» نیست؛ کاربر ممکن است
        در صفحهٔ درگاه پرداخت کرده باشد و هرگز برنگشته باشد. اکنون چنین
        پرداخت‌هایی ``ABANDONED`` می‌شوند: وضعیت «وضعیت پول نامعلوم است»،
        و توسط ``reconcile_abandoned_payments`` با درگاه داوری می‌شوند.
    """
    now = timezone.now()
    qs = Contribution.objects.select_for_update().filter(
        status=ContributionStatus.RESERVED,
        hold_expires_at__lte=now,
    )
    if campaign_id is not None:
        qs = qs.filter(campaign_id=campaign_id)

    expired_items = list(qs.order_by("id"))
    if not expired_items:
        return 0

    campaign_decrements: dict[Any, int] = {}
    contrib_ids = []
    for item in expired_items:
        contrib_ids.append(item.id)
        if item.campaign_id is not None and item.shares_count > 0:
            campaign_decrements[item.campaign_id] = (
                campaign_decrements.get(item.campaign_id, 0) + item.shares_count
            )

    for cid in sorted(campaign_decrements.keys(), key=str):
        dec = campaign_decrements[cid]
        locked_camp = Campaign.objects.select_for_update().filter(pk=cid).first()
        if locked_camp is not None:
            new_reserved = max(0, int(locked_camp.reserved_shares) - dec)
            locked_camp.reserved_shares = new_reserved
            locked_camp.save(update_fields=["reserved_shares", "updated_at"])

    Contribution.objects.filter(id__in=contrib_ids).update(
        status=ContributionStatus.EXPIRED,
        updated_at=now,
    )
    # پرداخت‌های معلق ⇒ «رها‌شده» (نه «ناموفق»): وضعیت پول هنوز نامعلوم است.
    abandoned = Payment.objects.filter(
        contribution_id__in=contrib_ids,
        status=PaymentStatus.INITIATED,
    )
    abandoned_ids = list(abandoned.values_list("id", flat=True))
    abandoned.update(status=PaymentStatus.ABANDONED, updated_at=now)
    if abandoned_ids:
        PaymentEvent.objects.bulk_create(
            [
                PaymentEvent(
                    payment_id=pid,
                    event_type="abandoned",
                    raw_status="HOLD_EXPIRED",
                    details={"reason": "hold_expired", "queued_for_reconciliation": True},
                )
                for pid in abandoned_ids
            ]
        )

    transaction.on_commit(lambda: bump_epoch("campaigns"))
    return len(contrib_ids)


def _create_dedication_card_for_contribution(
    *,
    contribution: Contribution,
    payload: dict[str, Any],
) -> DedicationCard:
    """ایجاد رکورد گواهی نیت‌نامه (غیرفعال تا لحظه پرداخت موفق)."""
    if not is_feature_enabled("feature.spiritual_dedications"):
        raise FeatureDisabledError("قابلیت صدور نیت‌نامه و کارت هدیه معنوی غیرفعال است.")

    honoree = str(payload.get("honoree_name") or "").strip()
    if not honoree:
        raise DomainValidationError("نام فرد تقدیم‌شونده (به نام / به یادِ) در نیت‌نامه الزامی است.")

    raw_recipient = str(payload.get("recipient_phone") or "").strip()
    recipient_phone = normalize_phone(raw_recipient) if raw_recipient else ""

    token = secrets.token_urlsafe(18).replace("-", "a").replace("_", "b")[:26]
    dedication_type = str(payload.get("dedication_type") or "in_memory")
    sig = _sign_artifact(
        "dedication.v1",
        f"{contribution.id}|{token}|{dedication_type}|{honoree}",
    )
    return DedicationCard.objects.create(
        contribution=contribution,
        dedication_type=dedication_type,
        honoree_name=honoree[:140],
        dedicator_display_name=str(payload.get("dedicator_display_name") or "").strip()[:140],
        message=str(payload.get("message") or "").strip()[:320],
        recipient_phone=recipient_phone,
        public_token=token,
        signature_hmac=sig,
        is_active=False,
    )


def _resolve_ambassador_for_checkout(
    *,
    ambassador_code: str,
    campaign_id: Any = None,
    jar_id: Any = None,
) -> AmbassadorLink | None:
    """واکشی لینک سفیر معتبر در صورت تطابق با حرکت یا قلک هدف."""
    code = ambassador_code.strip()
    if not code or not is_feature_enabled("feature.shortlinks_and_ambassadors"):
        return None
    amb = AmbassadorLink.objects.filter(code=code, is_active=True).first()
    if amb is None:
        return None
    if campaign_id and str(amb.campaign_id) == str(campaign_id):
        return amb
    if jar_id and str(amb.charity_jar_id) == str(jar_id):
        return amb
    return None


def checkout_pledge_installment(
    *,
    installment: Any,
    pledge: Any,
    user: User,
    request: Any = None,
) -> dict[str, Any]:
    """پرداخت یک قسط تعهد مستمر از مسیر checkout موجود — بدون موتور پرداخت تازه.

    این تابع همان ``initiate_contribution_checkout`` را صدا می‌زند که خیر در
    کمک یک‌باره استفاده می‌کند. تفاوت فقط در دو کار پس از آن:

      ۱. مشارکت به تعهد پیوند می‌خورد (``Contribution.pledge``).
      ۲. قسط به مشارکت پیوند می‌خورد تا پس از تأیید درگاه تسویه شود.

    قسط در این مرحله **پرداخت‌شده نمی‌شود**. ``PAID`` شدن فقط پس از تأیید
    درگاه و در ``settle_pledge_installment_after_verify`` رخ می‌دهد. این
    تفکیک، درس مستقیم فاز ۳ است: «کاربر به درگاه رفت» با «پول رسید» یکی نیست.
    """
    # عمداً هیچ ``@transaction.atomic`` روی این تابع نیست.
    # دلیل: ``initiate_contribution_checkout`` خودش تراکنش خود را باز و می‌بندد.
    # اگر این تابع هم atomic بود و فراخوان از قبل تراکنشی باز داشت (مثل تست
    # همروندی)، قفل‌های ``select_for_update`` در لایهٔ بیرونی می‌شکنند و
    # ``TransactionManagementError`` می‌دهند. عملیات اینجا دو نوشتن ساده است
    # که هر کدام atomic مستقل خود را دارند.
    from apps.contributions.recurring import link_installment_to_contribution

    gateway = str(getattr(request, "data", {}).get("gateway_name") or "") if request else ""

    contribution, payment = initiate_contribution_checkout(
        user=user,
        target_kind=str(pledge.target_kind),
        campaign_id=str(pledge.campaign_id) if pledge.campaign_id else None,
        charity_jar_id=str(pledge.charity_jar_id) if pledge.charity_jar_id else None,
        shares_count=int(installment.shares_count) if installment.shares_count else 0,
        amount_rial=int(installment.amount_rial),
        gateway_name=gateway or None,
        request=request,
    )

    link_installment_to_contribution(installment_id=installment.pk, contribution=contribution)

    return {
        "installment_id": str(installment.pk),
        "contribution_id": str(contribution.pk),
        "payment_id": str(payment.pk),
        "amount_rial": int(installment.amount_rial),
        # نام فیلد مدل ``redirect_url`` است. استفاده از نام اشتباه، لینک
        # درگاه را خالی برمی‌گرداند و خیر روی صفحه‌ای بدون دکمه می‌ماند —
        # خطای خاموشی که فقط در تست یکپارچگی گرفته می‌شود.
        "redirect_url": str(getattr(payment, "redirect_url", "") or ""),
    }


@transaction.atomic
def initiate_contribution_checkout(
    *,
    user: User,
    target_kind: str,
    campaign_id: str | None = None,
    charity_jar_id: str | None = None,
    shares_count: int = 0,
    amount_rial: int = 0,
    is_anonymous: bool = False,
    public_note: str = "",
    ambassador_code: str = "",
    dedication_payload: dict[str, Any] | None = None,
    gateway_name: str | None = None,
    request: Any = None,
) -> tuple[Contribution, Payment]:
    """رزرو اتمیک ۱۵ دقیقه‌ای سهم (یا ثبت واریز قلک) و دریافت لینک هدایت به درگاه پرداخت."""
    raw_req = getattr(request, "_request", request) if request is not None else None
    ip_raw = client_ip(raw_req) if raw_req is not None else ""
    ip_hash = blind_index(ip_raw, namespace="pay-ip") if ip_raw else ""

    # ابتدا هرگونه رزرو منقضی‌شدهٔ قبلی را آزاد می‌کنیم تا ظرفیت واقعی در دسترس باشد
    release_expired_share_holds(campaign_id=campaign_id)

    max_active_holds = int(get_policy("share.max_active_holds_per_user"))
    active_user_holds = Contribution.objects.filter(
        user=user,
        status=ContributionStatus.RESERVED,
        hold_expires_at__gt=timezone.now(),
    ).count()
    if active_user_holds >= max_active_holds:
        PaymentRiskSignal.objects.create(
            user=user,
            kind=PaymentRiskKind.HOLD_HOARDING_BLOCKED,
            ip_hash=ip_hash,
            details={"active_holds": active_user_holds},
        )
        raise RateLimitedError(
            f"شما هم‌اکنون {active_user_holds} سفارش در انتظار پرداخت دارید. لطفاً ابتدا آن‌ها را تعیین تکلیف کنید."
        )

    if is_anonymous and not is_feature_enabled("feature.anonymous_and_live_feed"):
        raise FeatureDisabledError("امکان مشارکت ناشناس در سیاست فعلی سامانه غیرفعال است.")

    hold_minutes = int(get_policy("share.hold_ttl_minutes"))
    now = timezone.now()
    hold_expires_at = now + timedelta(minutes=hold_minutes)

    campaign: Campaign | None = None
    jar: CharityJar | None = None
    benefactor: Benefactor

    if target_kind == ContributionTargetKind.CAMPAIGN_SHARES:
        if not campaign_id:
            raise DomainValidationError("شناسهٔ حرکت برای خرید سهم الزامی است.")
        campaign = (
            Campaign.objects.select_for_update()
            .select_related("benefactor")
            .filter(pk=campaign_id)
            .first()
        )
        if campaign is None or not campaign.benefactor.is_active:
            raise NotFoundError("حرکت مورد نظر یافت نشد.")
        if campaign.status != CampaignStatus.ACTIVE:
            raise ConflictError("این حرکت در حال حاضر در وضعیت جذب مشارکت فعال نیست.")
        if campaign.ends_at and campaign.ends_at <= now:
            raise ConflictError("مهلت زمانی مشارکت در این حرکت به پایان رسیده است.")
        if is_anonymous and not campaign.allow_anonymous:
            raise DomainValidationError("مشارکت ناشناس برای این حرکت غیرفعال است.")
        if dedication_payload and not campaign.allow_dedication:
            raise DomainValidationError("ثبت نیت‌نامه برای این حرکت غیرفعال است.")

        if shares_count < campaign.min_shares_per_order:
            raise DomainValidationError(
                f"حداقل تعداد مجاز در هر سفارش {campaign.min_shares_per_order} سهم است."
            )
        if campaign.max_shares_per_order > 0 and shares_count > campaign.max_shares_per_order:
            raise DomainValidationError(
                f"حداکثر تعداد مجاز در هر سفارش {campaign.max_shares_per_order} سهم است."
            )
        if shares_count > campaign.remaining_shares:
            raise ConflictError(
                f"تنها {campaign.remaining_shares} سهم آزاد در این حرکت باقی مانده است."
            )

        final_amount_rial = int(shares_count) * int(campaign.share_price_rial)
        campaign.reserved_shares = int(campaign.reserved_shares) + int(shares_count)
        campaign.save(update_fields=["reserved_shares", "updated_at"])
        benefactor = campaign.benefactor
        gw_description = f"مشارکت {shares_count} سهم در حرکت «{campaign.title}»"
    elif target_kind == ContributionTargetKind.CHARITY_JAR:
        if not is_feature_enabled("feature.charity_general_jars"):
            raise FeatureDisabledError("قابلیت قلک عام خیریه در حال حاضر غیرفعال است.")
        if not charity_jar_id:
            raise DomainValidationError("شناسهٔ قلک عام برای واریز آزاد الزامی است.")
        jar = (
            CharityJar.objects.select_for_update()
            .select_related("benefactor")
            .filter(pk=charity_jar_id, is_active=True, benefactor__is_active=True)
            .first()
        )
        if jar is None:
            raise NotFoundError("قلک عام مورد نظر یافت نشد یا غیرفعال است.")
        if amount_rial < jar.min_amount_rial or amount_rial > jar.max_amount_rial:
            raise DomainValidationError(
                f"مبلغ واریز به این قلک باید بین {jar.min_amount_rial:,} تا {jar.max_amount_rial:,} ریال باشد."
            )
        shares_count = 0
        final_amount_rial = int(amount_rial)
        benefactor = jar.benefactor
        gw_description = f"واریز آزاد به قلک «{jar.title}» ({benefactor.name})"
    else:
        raise DomainValidationError("نوع مقصد مشارکت نامعتبر است.")

    amb_link = _resolve_ambassador_for_checkout(
        ambassador_code=ambassador_code,
        campaign_id=campaign.id if campaign else None,
        jar_id=jar.id if jar else None,
    )

    contribution = Contribution.objects.create(
        user=user,
        benefactor=benefactor,
        target_kind=target_kind,
        campaign=campaign,
        charity_jar=jar,
        ambassador_link=amb_link,
        shares_count=shares_count,
        amount_rial=final_amount_rial,
        is_anonymous=is_anonymous,
        public_note=public_note.strip()[:200],
        status=ContributionStatus.RESERVED,
        hold_expires_at=hold_expires_at,
    )

    if dedication_payload:
        _create_dedication_card_for_contribution(
            contribution=contribution,
            payload=dedication_payload,
        )

    callback_base = str(
        getattr(settings, "PAYMENT_CALLBACK_URL", "http://localhost:8000/api/v1/payments/callback")
    )
    gw_port = resolve_payment_gateway(gateway_name)
    gw_init = gw_port.initiate(
        amount_rial=final_amount_rial,
        callback_url=callback_base,
        description=gw_description,
        mobile=user.phone,
    )

    payment = Payment.objects.create(
        contribution=contribution,
        gateway_name=gw_init.gateway_name,
        authority=gw_init.authority,
        amount_rial=final_amount_rial,
        redirect_url=gw_init.redirect_url,
        status=PaymentStatus.INITIATED,
    )
    PaymentEvent.objects.create(
        payment=payment,
        event_type="initiated",
        raw_status="100",
        details={
            "redirect_url": gw_init.redirect_url,
            "hold_expires_at": hold_expires_at.isoformat(),
        },
    )

    transaction.on_commit(lambda: bump_epoch("campaigns"))
    return contribution, payment


# ── ایده ۱: مشارکت سریع ۳۰ ثانیه‌ای مهمان (Express One-Step Checkout) ─────────


@transaction.atomic
def start_express_checkout(
    *,
    data: dict[str, Any],
    request: Any = None,
) -> dict[str, Any]:
    """گام اول مشارکت سریع ۳۰ ثانیه‌ای: ذخیرهٔ نیت خرید و ارسال هم‌زمان کد یک‌بارمصرف پیامکی."""
    if not is_feature_enabled("feature.express_one_step_checkout"):
        raise FeatureDisabledError("مسیر مشارکت سریع مهمان در حال حاضر غیرفعال است.")

    phone = normalize_phone(str(data["phone"]))
    target_kind = str(data.get("target_kind") or ContributionTargetKind.CAMPAIGN_SHARES)

    campaign = None
    jar = None
    shares_count = int(data.get("shares_count") or 0)
    amount_rial = int(data.get("amount_rial") or 0)

    if target_kind == ContributionTargetKind.CAMPAIGN_SHARES:
        camp_pk = str(data.get("campaign_id") or "")
        campaign = (
            Campaign.objects.filter(pk=camp_pk, status=CampaignStatus.ACTIVE).first()
            if camp_pk
            else None
        )
        if campaign is None:
            raise NotFoundError("حرکت انتخاب‌شده فعال نیست یا یافت نشد.")
        release_expired_share_holds(campaign_id=campaign.id)
        campaign.refresh_from_db()
        if shares_count < 1 or shares_count > campaign.remaining_shares:
            raise ConflictError("تعداد سهم انتخاب‌شده در حال حاضر در دسترس نیست.")
        amount_rial = shares_count * int(campaign.share_price_rial)
    else:
        if not is_feature_enabled("feature.charity_general_jars"):
            raise FeatureDisabledError("قابلیت قلک عام غیرفعال است.")
        jar_pk = str(data.get("charity_jar_id") or "")
        jar = CharityJar.objects.filter(pk=jar_pk, is_active=True).first() if jar_pk else None
        if jar is None:
            raise NotFoundError("قلک عام یافت نشد.")
        if amount_rial < jar.min_amount_rial or amount_rial > jar.max_amount_rial:
            raise DomainValidationError("مبلغ انتخاب‌شده خارج از بازهٔ مجاز قلک است.")
        shares_count = 0

    raw_req = getattr(request, "_request", request) if request is not None else None
    challenge, raw_code = request_otp(
        phone_raw=phone,
        purpose=OtpPurpose.EXPRESS_CHECKOUT,
        request=raw_req,
    )
    intent = ExpressContributionIntent.objects.create(
        phone=phone,
        display_name=str(data.get("display_name") or "").strip()[:120],
        target_kind=target_kind,
        campaign=campaign,
        charity_jar=jar,
        shares_count=shares_count,
        amount_rial=amount_rial,
        is_anonymous=bool(data.get("is_anonymous", False)),
        public_note=str(data.get("public_note") or "").strip()[:200],
        ambassador_code=str(data.get("ambassador_code") or "").strip()[:20],
        gateway_name=str(data.get("gateway_name") or GatewayName.SANDBOX),
        dedication_payload=dict(data.get("dedication") or {}),
        otp_challenge_id=challenge.id,
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    result: dict[str, Any] = {
        "intent_id": str(intent.id),
        "expires_in": OTP_TTL_SECONDS,
        "amount_rial": amount_rial,
        "shares_count": shares_count,
    }
    if getattr(settings, "EXPOSE_DEV_OTP_CODE", False):
        result["dev_code"] = raw_code
    return result


@transaction.atomic
def confirm_express_checkout(
    *,
    intent_id: str,
    otp_code: str,
    request: Any = None,
) -> tuple[IssuedAuthTokens, Contribution, Payment]:
    """گام دوم مشارکت سریع ۳۰ ثانیه‌ای: تأیید OTP + ساخت نشست کامل + رزرو سهم + لینک مستقیم درگاه."""
    if not is_feature_enabled("feature.express_one_step_checkout"):
        raise FeatureDisabledError("مسیر مشارکت سریع مهمان در حال حاضر غیرفعال است.")

    intent = ExpressContributionIntent.objects.select_for_update().filter(pk=intent_id).first()
    if intent is None or intent.consumed_at is not None or intent.expires_at <= timezone.now():
        raise ConflictError("نیت مشارکت سریع منقضی یا پیش‌تر مصرف شده است؛ دوباره اقدام کنید.")

    raw_req = getattr(request, "_request", request) if request is not None else None
    user = verify_otp_and_get_user(
        phone_raw=intent.phone,
        code_raw=otp_code,
        purpose=OtpPurpose.EXPRESS_CHECKOUT,
        request=raw_req,
    )
    if intent.display_name and not user.full_name:
        parts = intent.display_name.split(maxsplit=1)
        user.first_name = parts[0][:80]
        user.last_name = parts[1][:80] if len(parts) > 1 else ""
        user.save(update_fields=["first_name", "last_name", "updated_at"])

    assert raw_req is not None
    auth_bundle = establish_dual_session(user=user, request=raw_req)

    contribution, payment = initiate_contribution_checkout(
        user=user,
        target_kind=intent.target_kind,
        campaign_id=str(intent.campaign_id) if intent.campaign_id else None,
        charity_jar_id=str(intent.charity_jar_id) if intent.charity_jar_id else None,
        shares_count=intent.shares_count,
        amount_rial=intent.amount_rial,
        is_anonymous=intent.is_anonymous,
        public_note=intent.public_note,
        ambassador_code=intent.ambassador_code,
        dedication_payload=intent.dedication_payload or None,
        gateway_name=intent.gateway_name,
        request=request,
    )
    intent.consumed_at = timezone.now()
    intent.save(update_fields=["consumed_at", "updated_at"])
    return auth_bundle, contribution, payment


# ── تایید بازگشت درگاه پرداخت، دفترکل دوطرفه، رسید، نیت‌نامه و درخت مرکل ─────


def _issue_signed_receipt(*, contribution: Contribution) -> DonationReceipt:
    """صدور رسید رسمی با شماره یکتا و امضای رمزنگاری HMAC-SHA256."""
    existing = DonationReceipt.objects.filter(contribution=contribution).first()
    if existing is not None:
        return existing

    serialize_on("receipt.sequence")
    seq_count = DonationReceipt.objects.count() + 1
    jalali_prefix = timezone.now().strftime("%Y%m")
    receipt_number = f"CF-{jalali_prefix}-{seq_count:06d}"
    verification_code = f"VRF-{secrets.token_hex(8).upper()}"
    sig = _sign_artifact(
        "receipt.v1",
        f"{receipt_number}|{verification_code}|{contribution.id}|{contribution.amount_rial}|{contribution.shares_count}",
    )
    return DonationReceipt.objects.create(
        contribution=contribution,
        receipt_number=receipt_number,
        verification_code=verification_code,
        signature_hmac=sig,
    )


def build_or_refresh_campaign_merkle_snapshot(*, campaign_id: Any) -> CampaignTransparencySnapshot:
    """محاسبهٔ مجدد ریشهٔ درخت مرکل (Merkle Root) برای تمام مشارکت‌های قطعی یک حرکت."""
    campaign = Campaign.objects.get(pk=campaign_id)
    paid_qs = (
        Contribution.objects.select_related("receipt")
        .filter(
            campaign_id=campaign.id,
            status=ContributionStatus.PAID,
        )
        .order_by("paid_at", "id")
    )

    secret_salt = str(getattr(settings, "AUDIT_ANCHOR_HMAC_KEY", settings.SECRET_KEY))
    leaf_hashes: list[str] = []
    online_shares = 0
    matched_shares = 0
    online_rial = 0

    for c in paid_qs:
        vcode = c.receipt.verification_code if hasattr(c, "receipt") else str(c.id)
        leaf_hashes.append(
            compute_leaf_hash(
                MerkleLeafInput(
                    contribution_id=str(c.id),
                    receipt_verification_code=vcode,
                    shares_count=int(c.shares_count),
                    matched_shares=int(c.matched_shares_awarded),
                    amount_rial=int(c.amount_rial),
                ),
                secret_salt=secret_salt,
            )
        )
        online_shares += int(c.shares_count)
        matched_shares += int(c.matched_shares_awarded)
        online_rial += int(c.amount_rial)

    levels = build_merkle_levels(leaf_hashes)
    merkle_root = levels[-1][0]
    sig = _sign_artifact(
        "merkle.v1",
        f"{campaign.id}|{merkle_root}|{len(leaf_hashes)}|{online_shares}|{online_rial}",
    )
    return CampaignTransparencySnapshot.objects.create(
        campaign=campaign,
        merkle_root=merkle_root,
        leaf_count=len(leaf_hashes),
        online_shares_total=online_shares,
        matched_shares_total=matched_shares,
        online_amount_rial=online_rial,
        signature_hmac=sig,
    )


def get_donor_merkle_inclusion_proof(*, user: User, contribution_id: str) -> dict[str, Any]:
    """استخراج مسیر اثبات شمول رمزنگاری‌شده (Merkle Inclusion Proof) برای یک مشارکت خیر."""
    if not is_feature_enabled("feature.merkle_transparency"):
        raise FeatureDisabledError("قابلیت اثبات شفافیت مرکل در حال حاضر غیرفعال است.")

    target = (
        Contribution.objects.select_related("campaign", "receipt")
        .filter(pk=contribution_id, user=user, status=ContributionStatus.PAID)
        .first()
    )
    if target is None or target.campaign is None:
        raise NotFoundError("مشارکت قطعی سهم‌محور یافت نشد.")

    paid_list = list(
        Contribution.objects.select_related("receipt")
        .filter(campaign=target.campaign, status=ContributionStatus.PAID)
        .order_by("paid_at", "id")
    )
    secret_salt = str(getattr(settings, "AUDIT_ANCHOR_HMAC_KEY", settings.SECRET_KEY))
    leaf_hashes: list[str] = []
    target_idx = -1
    for idx, c in enumerate(paid_list):
        if c.id == target.id:
            target_idx = idx
        vcode = c.receipt.verification_code if hasattr(c, "receipt") else str(c.id)
        leaf_hashes.append(
            compute_leaf_hash(
                MerkleLeafInput(
                    contribution_id=str(c.id),
                    receipt_verification_code=vcode,
                    shares_count=int(c.shares_count),
                    matched_shares=int(c.matched_shares_awarded),
                    amount_rial=int(c.amount_rial),
                ),
                secret_salt=secret_salt,
            )
        )

    if target_idx < 0:
        raise NotFoundError("برگ متناظر در درخت شفافیت یافت نشد.")

    root_hash, proof_steps = generate_inclusion_proof(leaf_hashes, target_idx)
    leaf_hash = leaf_hashes[target_idx]
    return {
        "contribution_id": str(target.id),
        "campaign_id": str(target.campaign_id),
        "campaign_slug": target.campaign.slug,
        "leaf_index": target_idx,
        "total_leaves": len(leaf_hashes),
        "leaf_hash": leaf_hash,
        "merkle_root": root_hash,
        "proof": proof_steps,
        "verified": verify_inclusion_proof(
            leaf_hash=leaf_hash,
            proof=proof_steps,
            expected_root=root_hash,
        ),
    }


@transaction.atomic
def verify_payment_callback(
    *,
    authority: str,
    gateway_status: str = "OK",
) -> tuple[Payment, DonationReceipt | None]:
    """تأیید نهایی تکرارناپذیر (Idempotent) بازگشت از درگاه پرداخت، ثبت دفترکل، مضاعف‌سازی و صدور رسید."""
    payment = (
        Payment.objects.select_for_update()
        .select_related("contribution", "contribution__user", "contribution__benefactor")
        .filter(authority=authority)
        .first()
    )
    if payment is None:
        raise NotFoundError("تراکنش درگاه با این شناسه Authority یافت نشد.")

    contribution = (
        Contribution.objects.select_for_update()
        .select_related("user", "benefactor")
        .get(pk=payment.contribution_id)
    )

    # تکرارپذیری کامل (Idempotency): اگر پیش‌تر تأیید شده، همان نتیجه را برمی‌گرداند
    if payment.status == PaymentStatus.VERIFIED and contribution.status == ContributionStatus.PAID:
        receipt = DonationReceipt.objects.filter(contribution=contribution).first()
        return payment, receipt

    if payment.status == PaymentStatus.REFUNDED:
        raise ConflictError("این تراکنش پیش‌تر مسترد شده است.")

    now = timezone.now()
    if gateway_status.upper() not in {"OK", "SUCCESS", "100", "VERIFIED"}:
        _release_failed_payment(
            payment=payment, contribution=contribution, raw_status=gateway_status
        )
        return payment, None

    gw_port = resolve_payment_gateway(payment.gateway_name)
    verify_res = gw_port.verify(authority=payment.authority, amount_rial=int(payment.amount_rial))
    if not verify_res.verified:
        _release_failed_payment(
            payment=payment,
            contribution=contribution,
            raw_status=verify_res.raw_code or "VERIFY_FAILED",
        )
        return payment, None

    benefactor = Benefactor.objects.select_for_update().get(pk=contribution.benefactor_id)
    matched_shares = 0
    matched_rial = 0
    applied_grant: MatchingGrant | None = None
    target_title = benefactor.name

    if contribution.target_kind == ContributionTargetKind.CAMPAIGN_SHARES:
        if contribution.campaign_id is None:
            raise ConflictError("مشارکت سهم‌محور فاقد حرکت مرتبط است.")
        campaign = Campaign.objects.select_for_update().get(pk=contribution.campaign_id)
        target_title = campaign.title

        if contribution.status == ContributionStatus.RESERVED:
            campaign.reserved_shares = max(
                0, int(campaign.reserved_shares) - int(contribution.shares_count)
            )
        elif contribution.status in {
            ContributionStatus.EXPIRED,
            ContributionStatus.FAILED,
        } and campaign.remaining_shares < int(contribution.shares_count):
            raise ConflictError(
                "سهم رزروشده منقضی شده و ظرفیت حرکت پر شده است؛ وجه جهت استرداد خودکار علامت‌گذاری شد."
            )

        # بررسی و اعمال حامی مضاعف‌کننده (Idea #8: Matching Grants)
        if is_feature_enabled("feature.matching_grants"):
            grant = (
                MatchingGrant.objects.select_for_update()
                .filter(
                    campaign=campaign,
                    is_active=True,
                    consumed_shares__lt=F("total_pool_shares"),
                )
                .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
                .order_by("created_at")
                .first()
            )
            if grant is not None:
                avail_after_donor = max(
                    0,
                    int(campaign.total_shares)
                    - (int(campaign.funded_shares) + int(contribution.shares_count))
                    - int(campaign.reserved_shares),
                )
                desired_match = int(contribution.shares_count) * int(grant.match_ratio)
                matched_shares = min(desired_match, grant.remaining_pool_shares, avail_after_donor)
                if matched_shares > 0:
                    matched_rial = matched_shares * int(campaign.share_price_rial)
                    grant.consumed_shares = int(grant.consumed_shares) + matched_shares
                    grant.save(update_fields=["consumed_shares", "updated_at"])
                    applied_grant = grant

        campaign.paid_shares = int(campaign.paid_shares) + int(contribution.shares_count)
        campaign.matched_shares = int(campaign.matched_shares) + matched_shares
        campaign.collected_online_rial = int(campaign.collected_online_rial) + int(
            contribution.amount_rial
        )
        campaign.matched_amount_rial = int(campaign.matched_amount_rial) + matched_rial
        campaign.supporter_count = int(campaign.supporter_count) + 1

        if (
            campaign.funded_shares >= campaign.total_shares
            and campaign.status == CampaignStatus.ACTIVE
        ):
            campaign.status = CampaignStatus.COMPLETED
            campaign.completed_at = now

        campaign.save(
            update_fields=[
                "reserved_shares",
                "paid_shares",
                "matched_shares",
                "collected_online_rial",
                "matched_amount_rial",
                "supporter_count",
                "status",
                "completed_at",
                "updated_at",
            ]
        )
        sync_benefactor_campaign_counters(benefactor_id=benefactor.id)
    else:
        if contribution.charity_jar_id is None:
            raise ConflictError("مشارکت قلکی فاقد قلک عام مرتبط است.")
        jar = CharityJar.objects.select_for_update().get(pk=contribution.charity_jar_id)
        target_title = jar.title
        jar.total_raised_rial = int(jar.total_raised_rial) + int(contribution.amount_rial)
        jar.donor_count = int(jar.donor_count) + 1
        jar.save(update_fields=["total_raised_rial", "donor_count", "updated_at"])

    benefactor.total_raised_rial = (
        int(benefactor.total_raised_rial) + int(contribution.amount_rial) + matched_rial
    )
    benefactor.save(update_fields=["total_raised_rial", "updated_at"])

    # ثبت سند روزنامهٔ دوطرفهٔ وصول وجه آنلاین درگاه
    ben_code, ben_title, ben_type = benefactor_online_payable_spec(benefactor)
    post_journal_entry(
        reference_key=f"payment.verified:{payment.id}",
        kind=JournalEntryKind.CONTRIBUTION_PAID,
        description=f"وصول مشارکت آنلاین ({target_title}) — پیگیری {verify_res.ref_id}",
        campaign_id=contribution.campaign_id,
        benefactor_id=benefactor.id,
        actor=contribution.user,
        metadata={"payment_id": str(payment.id), "ref_id": verify_res.ref_id},
        lines=[
            PostingLineSpec(
                account_code=ACC_GATEWAY_RECEIVABLE,
                account_title="دریافتنی درگاه پرداخت آنلاین",
                account_type=LedgerAccountType.ASSET,
                debit_rial=int(contribution.amount_rial),
                memo=f"Authority {payment.authority}",
            ),
            PostingLineSpec(
                account_code=ben_code,
                account_title=ben_title,
                account_type=ben_type,
                credit_rial=int(contribution.amount_rial),
                benefactor_id=benefactor.id,
                memo=f"مشارکت {contribution.id}",
            ),
        ],
    )

    # ثبت سند روزنامهٔ مجزا در صورت فعال شدن سهم حامی مضاعف‌کننده
    if matched_rial > 0 and applied_grant is not None:
        post_journal_entry(
            reference_key=f"payment.matched:{payment.id}",
            kind=JournalEntryKind.MATCHING_GRANT_APPLIED,
            description=f"اعمال {matched_shares} سهم مضاعف از تعهد {applied_grant.sponsor_name}",
            campaign_id=contribution.campaign_id,
            benefactor_id=benefactor.id,
            actor=contribution.user,
            metadata={"grant_id": str(applied_grant.id), "matched_shares": matched_shares},
            lines=[
                PostingLineSpec(
                    account_code=ACC_MATCHING_POOL,
                    account_title="حساب تعهد حامیان مضاعف‌کننده",
                    account_type=LedgerAccountType.ASSET,
                    debit_rial=matched_rial,
                    memo=applied_grant.sponsor_name,
                ),
                PostingLineSpec(
                    account_code=ben_code,
                    account_title=ben_title,
                    account_type=ben_type,
                    credit_rial=matched_rial,
                    benefactor_id=benefactor.id,
                    memo=f"مضاعف مشارکت {contribution.id}",
                ),
            ],
        )

    contribution.status = ContributionStatus.PAID
    contribution.paid_at = now
    contribution.matched_shares_awarded = matched_shares
    contribution.matched_amount_rial = matched_rial
    contribution.applied_matching_grant = applied_grant
    contribution.save(
        update_fields=[
            "status",
            "paid_at",
            "matched_shares_awarded",
            "matched_amount_rial",
            "applied_matching_grant",
            "updated_at",
        ]
    )

    payment.status = PaymentStatus.VERIFIED
    payment.ref_id = verify_res.ref_id
    payment.card_pan_masked = verify_res.card_pan_masked
    payment.verified_at = now
    payment.save(update_fields=["status", "ref_id", "card_pan_masked", "verified_at", "updated_at"])
    PaymentEvent.objects.create(
        payment=payment,
        event_type="verified",
        raw_status=verify_res.raw_code,
        details={"ref_id": verify_res.ref_id, "matched_shares": matched_shares},
    )

    receipt = _issue_signed_receipt(contribution=contribution)

    # فعال‌سازی نیت‌نامه و ارسال پیامک کارت هدیه معنوی در صورت وجود
    dedication = DedicationCard.objects.filter(contribution=contribution).first()
    if dedication is not None:
        dedication.is_active = True
        dedication.save(update_fields=["is_active", "updated_at"])
        if dedication.recipient_phone:
            base_pub = str(
                getattr(settings, "PUBLIC_APP_BASE_URL", "http://localhost:3000")
            ).rstrip("/")
            enqueue_outbox(
                event_type="sms.dedication_gift",
                aggregate_type="DedicationCard",
                aggregate_id=str(dedication.id),
                payload={
                    "recipient_phone": dedication.recipient_phone,
                    "honoree_name": dedication.honoree_name,
                    "campaign_title": target_title,
                    "public_url": f"{base_pub}/dedications/{dedication.public_token}",
                },
            )

    # ثبت اثرگذاری لینک سفیر اجتماعی (Idea #7)
    if contribution.ambassador_link_id is not None:
        AmbassadorLink.objects.filter(pk=contribution.ambassador_link_id).update(
            referred_donors_count=F("referred_donors_count") + 1,
            attributed_shares=F("attributed_shares") + int(contribution.shares_count),
            attributed_amount_rial=F("attributed_amount_rial") + int(contribution.amount_rial),
        )
        amb = AmbassadorLink.objects.get(pk=contribution.ambassador_link_id)
        if amb.user_id != contribution.user_id:
            create_user_notification(
                user_id=amb.user_id,
                kind=UserNotificationKind.AMBASSADOR_IMPACT,
                title="یک نیکوکار جدید با دعوت شما همراه شد!",
                body=f"از طریق لینک سفیر شما در «{target_title}» یک مشارکت موفق جدید به ثبت رسید.",
                action_url="/me/dashboard",
                metadata={"ambassador_code": amb.code, "shares": contribution.shares_count},
            )

    # اعلان درون‌برنامه‌ای و پیامک رسید برای خود خیر
    create_user_notification(
        user_id=contribution.user_id,
        kind=UserNotificationKind.RECEIPT_READY,
        title=f"رسید مشارکت شما در «{target_title}» صادر شد",
        body=(
            f"مشارکت شما با کد رهگیری {receipt.verification_code} با موفقیت ثبت شد."
            + (
                f" همچنین حامی مضاعف‌کننده {matched_shares} سهم دیگر به برکت مشارکت شما افزود!"
                if matched_shares > 0
                else ""
            )
        ),
        action_url=f"/receipts/{receipt.verification_code}",
        metadata={"receipt_number": receipt.receipt_number, "matched_shares": matched_shares},
    )
    enqueue_outbox(
        event_type="sms.receipt_issued",
        aggregate_type="DonationReceipt",
        aggregate_id=str(receipt.id),
        payload={
            "phone": contribution.user.phone,
            "campaign_title": target_title,
            "receipt_number": receipt.receipt_number,
        },
    )

    if contribution.campaign_id is not None and is_feature_enabled("feature.merkle_transparency"):
        build_or_refresh_campaign_merkle_snapshot(campaign_id=contribution.campaign_id)

    record_audit_event(
        action=AuditAction.PAYMENT_VERIFIED,
        actor=contribution.user,
        target_type="Payment",
        target_id=str(payment.id),
        metadata={
            "contribution_id": str(contribution.id),
            "amount_rial": int(contribution.amount_rial),
            "shares_count": int(contribution.shares_count),
            "matched_shares": matched_shares,
            "receipt_number": receipt.receipt_number,
        },
    )
    transaction.on_commit(lambda: bump_epoch("campaigns"))
    transaction.on_commit(lambda: bump_epoch("benefactors"))
    transaction.on_commit(lambda: bump_epoch("jars"))

    # ── تسویهٔ قسط تعهد مستمر، اگر این پرداخت از یک تعهد آمده باشد ───────────
    # چرا اینجاست و نه در نمای callback؟
    #   هر مسیری که پول را تأیید می‌کند باید قسط را هم تسویه کند — بازگشت
    #   کاربر، داوری کرون، و خوددرمانی لایهٔ حقیقت. اگر در نما بود، دو مسیر
    #   دیگر قسط را جا می‌گذاشتند و تعهد برای همیشه «پرداخت‌نشده» می‌ماند
    #   در حالی که پول رسیده بود — همان مغایرتی که فاز ۳ برای کشفش ساخته شد.
    #   ایمن است چون کاملاً idempotent است.
    _settle_pledge_installment_if_any(contribution=contribution)

    return payment, receipt


def _settle_pledge_installment_if_any(*, contribution: Contribution) -> None:
    """اگر مشارکت به یک قسط تعهد وصل است، قسط را تسویه می‌کند.

    خطا هرگز بی‌صدا رد نمی‌شود: پول رسیده و قسط تسویه نشده یعنی داده ناسازگار،
    پس ثبت می‌شود تا کرون/پنل حقیقت آن را ببیند. اما استثنا **بالا نمی‌رود** —
    پول تأییدشده نباید به‌خاطر یک نقص جانبی در قسط، بی‌اعتبار شود.
    """
    installment = (
        PledgeInstallment.objects.filter(contribution=contribution)
        .values_list("id", flat=True)
        .first()
    )
    if installment is None:
        return
    try:
        settle_installment_payment(installment_id=installment, contribution=contribution)
    except Exception as exc:
        logger.exception(
            "تسویهٔ قسط تعهد مستمر شکست خورد: installment=%s contribution=%s",
            installment,
            contribution.pk,
            exc_info=exc,
        )


def _release_failed_payment(
    *, payment: Payment, contribution: Contribution, raw_status: str
) -> None:
    """آزادسازی فوری سهم رزروشده در صورت انصراف کاربر یا عدم تأیید شاپرک."""
    now = timezone.now()
    if (
        contribution.status == ContributionStatus.RESERVED
        and contribution.campaign_id is not None
        and contribution.shares_count > 0
    ):
        camp = Campaign.objects.select_for_update().get(pk=contribution.campaign_id)
        camp.reserved_shares = max(0, int(camp.reserved_shares) - int(contribution.shares_count))
        camp.save(update_fields=["reserved_shares", "updated_at"])

    contribution.status = ContributionStatus.FAILED
    contribution.save(update_fields=["status", "updated_at"])
    payment.status = PaymentStatus.FAILED
    payment.save(update_fields=["status", "updated_at"])
    PaymentEvent.objects.create(
        payment=payment,
        event_type="failed",
        raw_status=raw_status[:40],
        details={"released_at": now.isoformat()},
    )
    transaction.on_commit(lambda: bump_epoch("campaigns"))


# ── ایده ۶: ثبت مشارکت خارج از درگاه آنلاین (External/Offline Contribution) ───


@transaction.atomic
def record_external_contribution(
    *,
    actor: User,
    campaign_id: str,
    shares_count: int,
    donor_display_name: str,
    reference_code: str,
    note: str = "",
    request: Any = None,
) -> ExternalContribution:
    """ثبت سهم‌های تأمین‌شده خارج از درگاه در حساب انتظامی مجزا بدون آلوده‌کردن حساب درگاه آنلاین."""
    if not is_feature_enabled("feature.external_offline_funding"):
        raise FeatureDisabledError("ثبت مشارکت خارجی در سیاست فعلی سامانه غیرفعال است.")

    ref = reference_code.strip()
    if ExternalContribution.objects.filter(reference_code=ref).exists():
        raise ConflictError("این شماره سند/فیش مرجع پیش‌تر ثبت شده است.")

    release_expired_share_holds(campaign_id=campaign_id)
    campaign = (
        Campaign.objects.select_for_update()
        .select_related("benefactor")
        .filter(pk=campaign_id)
        .first()
    )
    if campaign is None:
        raise NotFoundError("حرکت مورد نظر یافت نشد.")
    if shares_count < 1 or shares_count > campaign.remaining_shares:
        raise ConflictError(
            f"تعداد سهم خارجی ({shares_count}) بیش از ظرفیت آزاد فعلی حرکت ({campaign.remaining_shares}) است."
        )

    amount_rial = int(shares_count) * int(campaign.share_price_rial)
    ext = ExternalContribution.objects.create(
        campaign=campaign,
        shares_count=shares_count,
        amount_rial=amount_rial,
        donor_display_name=donor_display_name.strip()[:140] or "حامی مستقیم خیریه",
        reference_code=ref,
        note=note.strip()[:320],
        recorded_by=actor,
    )

    campaign.external_shares = int(campaign.external_shares) + int(shares_count)
    campaign.external_amount_rial = int(campaign.external_amount_rial) + amount_rial
    if campaign.funded_shares >= campaign.total_shares and campaign.status == CampaignStatus.ACTIVE:
        campaign.status = CampaignStatus.COMPLETED
        campaign.completed_at = timezone.now()

    campaign.save(
        update_fields=[
            "external_shares",
            "external_amount_rial",
            "status",
            "completed_at",
            "updated_at",
        ]
    )
    sync_benefactor_campaign_counters(benefactor_id=campaign.benefactor_id)

    # ثبت در حساب انتظامی مستقیم خیریه (کاملاً تفکیک‌شده از حساب دریافتنی درگاه آنلاین!)
    eq_code, eq_title, eq_type = benefactor_external_equity_spec(campaign.benefactor)
    post_journal_entry(
        reference_key=f"external.contrib:{ext.id}",
        kind=JournalEntryKind.EXTERNAL_CONTRIBUTION,
        description=f"ثبت {shares_count} سهم خارج از درگاه در حرکت «{campaign.title}» (مرجع {ref})",
        campaign_id=campaign.id,
        benefactor_id=campaign.benefactor_id,
        actor=actor,
        metadata={"reference_code": ref, "shares_count": shares_count},
        lines=[
            PostingLineSpec(
                account_code=ACC_EXTERNAL_CUSTODY,
                account_title="دارایی انتظامی وجوه مستقیم نزد خیریه‌ها",
                account_type=LedgerAccountType.ASSET,
                debit_rial=amount_rial,
                memo=f"سند مستقیم {ref}",
            ),
            PostingLineSpec(
                account_code=eq_code,
                account_title=eq_title,
                account_type=eq_type,
                credit_rial=amount_rial,
                benefactor_id=campaign.benefactor_id,
                memo=ext.donor_display_name,
            ),
        ],
    )

    record_audit_event(
        action=AuditAction.EXTERNAL_FUNDING_RECORDED,
        actor=actor,
        target_type="ExternalContribution",
        target_id=str(ext.id),
        metadata={
            "campaign_id": str(campaign.id),
            "shares_count": shares_count,
            "amount_rial": amount_rial,
            "reference_code": ref,
        },
        request=request,
    )
    transaction.on_commit(lambda: bump_epoch("campaigns"))
    transaction.on_commit(lambda: bump_epoch("benefactors"))
    return ext


# ── استرداد وجه با سند معکوس دفترکل و احراز هویت چندعاملی تازه ───────────────


@transaction.atomic
def refund_verified_payment(
    *,
    actor: User,
    payment_id: str,
    reason: str,
    bank_reference: str = "",
    request: Any = None,
) -> PaymentRefund:
    """استرداد وجه یک پرداخت تاییدشده به همراه آزادسازی سهم‌ها و ثبت سند معکوس در دفترکل."""
    payment = (
        Payment.objects.select_for_update()
        .select_related("contribution")
        .filter(pk=payment_id)
        .first()
    )
    if payment is None:
        raise NotFoundError("پرداخت مورد نظر یافت نشد.")
    if payment.status != PaymentStatus.VERIFIED:
        raise ConflictError("فقط پرداخت‌های تاییدشده قابل استرداد هستند.")

    contribution = Contribution.objects.select_for_update().get(pk=payment.contribution_id)
    benefactor = Benefactor.objects.select_for_update().get(pk=contribution.benefactor_id)

    matched_rial = int(contribution.matched_amount_rial)
    matched_shares = int(contribution.matched_shares_awarded)

    if contribution.target_kind == ContributionTargetKind.CAMPAIGN_SHARES:
        if contribution.campaign_id is None:
            raise ConflictError("مشارکت سهم‌محور فاقد حرکت مرتبط است.")
        campaign = Campaign.objects.select_for_update().get(pk=contribution.campaign_id)
        if (
            int(campaign.collected_online_rial)
            + int(campaign.matched_amount_rial)
            - int(campaign.disbursed_amount_rial)
            < int(contribution.amount_rial) + matched_rial
        ):
            raise ConflictError(
                "منابع این حرکت پیش‌تر با خیریه تسویه شده و امکان استرداد مستقیم پیش از تسویه برگشتی نیست."
            )

        campaign.paid_shares = max(0, int(campaign.paid_shares) - int(contribution.shares_count))
        campaign.matched_shares = max(0, int(campaign.matched_shares) - matched_shares)
        campaign.collected_online_rial = max(
            0, int(campaign.collected_online_rial) - int(contribution.amount_rial)
        )
        campaign.matched_amount_rial = max(0, int(campaign.matched_amount_rial) - matched_rial)
        campaign.supporter_count = max(0, int(campaign.supporter_count) - 1)
        if (
            campaign.status == CampaignStatus.COMPLETED
            and campaign.funded_shares < campaign.total_shares
        ):
            campaign.status = CampaignStatus.ACTIVE
            campaign.completed_at = None
        campaign.save(
            update_fields=[
                "paid_shares",
                "matched_shares",
                "collected_online_rial",
                "matched_amount_rial",
                "supporter_count",
                "status",
                "completed_at",
                "updated_at",
            ]
        )
        if contribution.applied_matching_grant_id and matched_shares > 0:
            MatchingGrant.objects.filter(pk=contribution.applied_matching_grant_id).update(
                consumed_shares=F("consumed_shares") - matched_shares
            )
        sync_benefactor_campaign_counters(benefactor_id=benefactor.id)
    else:
        if contribution.charity_jar_id is None:
            raise ConflictError("مشارکت قلکی فاقد قلک عام مرتبط است.")
        jar = CharityJar.objects.select_for_update().get(pk=contribution.charity_jar_id)
        jar.total_raised_rial = max(0, int(jar.total_raised_rial) - int(contribution.amount_rial))
        jar.donor_count = max(0, int(jar.donor_count) - 1)
        jar.save(update_fields=["total_raised_rial", "donor_count", "updated_at"])

    benefactor.total_raised_rial = max(
        0, int(benefactor.total_raised_rial) - int(contribution.amount_rial) - matched_rial
    )
    benefactor.save(update_fields=["total_raised_rial", "updated_at"])

    ben_code, ben_title, ben_type = benefactor_online_payable_spec(benefactor)
    post_journal_entry(
        reference_key=f"payment.refund:{payment.id}",
        kind=JournalEntryKind.CONTRIBUTION_REFUNDED,
        description=f"استرداد وجه مشارکت {contribution.id} — علت: {reason[:120]}",
        campaign_id=contribution.campaign_id,
        benefactor_id=benefactor.id,
        actor=actor,
        lines=[
            PostingLineSpec(
                account_code=ben_code,
                account_title=ben_title,
                account_type=ben_type,
                debit_rial=int(contribution.amount_rial),
                benefactor_id=benefactor.id,
                memo="کسر بدهی خیریه بابت استرداد",
            ),
            PostingLineSpec(
                account_code=ACC_GATEWAY_RECEIVABLE,
                account_title="دریافتنی درگاه پرداخت آنلاین",
                account_type=LedgerAccountType.ASSET,
                credit_rial=int(contribution.amount_rial),
                memo=f"استرداد Authority {payment.authority}",
            ),
        ],
    )
    if matched_rial > 0:
        post_journal_entry(
            reference_key=f"payment.refund.match:{payment.id}",
            kind=JournalEntryKind.CONTRIBUTION_REFUNDED,
            description=f"برگشت سهم مضاعف مشارکت مستردشده {contribution.id}",
            campaign_id=contribution.campaign_id,
            benefactor_id=benefactor.id,
            actor=actor,
            lines=[
                PostingLineSpec(
                    account_code=ben_code,
                    account_title=ben_title,
                    account_type=ben_type,
                    debit_rial=matched_rial,
                    benefactor_id=benefactor.id,
                ),
                PostingLineSpec(
                    account_code=ACC_MATCHING_POOL,
                    account_title="حساب تعهد حامیان مضاعف‌کننده",
                    account_type=LedgerAccountType.ASSET,
                    credit_rial=matched_rial,
                ),
            ],
        )

    now = timezone.now()
    contribution.status = ContributionStatus.REFUNDED
    contribution.refunded_at = now
    contribution.save(update_fields=["status", "refunded_at", "updated_at"])
    payment.status = PaymentStatus.REFUNDED
    payment.save(update_fields=["status", "updated_at"])
    DedicationCard.objects.filter(contribution=contribution).update(is_active=False)

    refund = PaymentRefund.objects.create(
        payment=payment,
        amount_rial=int(contribution.amount_rial),
        reason=reason.strip()[:400],
        bank_reference=bank_reference.strip()[:80],
        refunded_by=actor,
    )

    if contribution.campaign_id is not None and is_feature_enabled("feature.merkle_transparency"):
        build_or_refresh_campaign_merkle_snapshot(campaign_id=contribution.campaign_id)

    record_audit_event(
        action=AuditAction.REFUND_APPROVED,
        actor=actor,
        target_type="PaymentRefund",
        target_id=str(refund.id),
        reason=reason,
        metadata={
            "payment_id": str(payment.id),
            "contribution_id": str(contribution.id),
            "amount_rial": int(contribution.amount_rial),
        },
        request=request,
    )
    transaction.on_commit(lambda: bump_epoch("campaigns"))
    transaction.on_commit(lambda: bump_epoch("benefactors"))
    transaction.on_commit(lambda: bump_epoch("jars"))
    return refund


# ── ایده ۷: لینک‌های سفیر اجتماعی (Social Ambassadors) ───────────────────────


@transaction.atomic
def create_ambassador_link(
    *,
    user: User,
    campaign_id: str | None = None,
    charity_jar_id: str | None = None,
    custom_note: str = "",
) -> AmbassadorLink:
    """ایجاد یا بازیابی لینک اختصاصی سفیر اجتماعی برای یک حرکت یا قلک عام."""
    if not is_feature_enabled("feature.shortlinks_and_ambassadors"):
        raise FeatureDisabledError("قابلیت سفیران اجتماعی در حال حاضر غیرفعال است.")

    if bool(campaign_id) == bool(charity_jar_id):
        raise DomainValidationError("دقیقاً یکی از شناسهٔ حرکت یا شناسهٔ قلک عام باید مشخص شود.")

    if campaign_id:
        camp = Campaign.objects.filter(pk=campaign_id).first()
        if camp is None:
            raise NotFoundError("حرکت مورد نظر یافت نشد.")
        existing = AmbassadorLink.objects.filter(user=user, campaign=camp).first()
        if existing is not None:
            if custom_note:
                existing.custom_note = custom_note.strip()[:240]
                existing.save(update_fields=["custom_note", "updated_at"])
            return existing
        target_camp = camp
        target_jar = None
    else:
        assert charity_jar_id is not None
        jar = CharityJar.objects.filter(pk=charity_jar_id, is_active=True).first()
        if jar is None:
            raise NotFoundError("قلک عام یافت نشد.")
        existing = AmbassadorLink.objects.filter(user=user, charity_jar=jar).first()
        if existing is not None:
            return existing
        target_camp = None
        target_jar = jar

    code = ""
    for _ in range(20):
        cand = "s-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(7))
        if not AmbassadorLink.objects.filter(code=cand).exists():
            code = cand
            break
    if not code:
        raise ConflictError("تولید کد سفیر ممکن نشد؛ دوباره تلاش کنید.")

    return AmbassadorLink.objects.create(
        user=user,
        campaign=target_camp,
        charity_jar=target_jar,
        code=code,
        custom_note=custom_note.strip()[:240],
    )


def try_resolve_and_track_ambassador_code(*, code: str) -> dict[str, Any] | None:
    """در صورتی که کد واردشده کد سفیر باشد، شمارندهٔ کلیک را افزایش داده و مقصد را برمی‌گرداند."""
    if not is_feature_enabled("feature.shortlinks_and_ambassadors"):
        return None
    amb = (
        AmbassadorLink.objects.select_related("campaign", "charity_jar")
        .filter(code=code, is_active=True)
        .first()
    )
    if amb is None:
        return None

    AmbassadorLink.objects.filter(pk=amb.pk).update(click_count=F("click_count") + 1)
    if amb.campaign is not None:
        return {
            "kind": "ambassador_campaign",
            "short_code": code,
            "slug": amb.campaign.slug,
            "title": amb.campaign.title,
            "target_path": f"/campaigns/{amb.campaign.slug}?ref={amb.code}",
            "ambassador_code": amb.code,
        }
    assert amb.charity_jar is not None
    return {
        "kind": "ambassador_jar",
        "short_code": code,
        "slug": amb.charity_jar.slug,
        "title": amb.charity_jar.title,
        "target_path": f"/jars/{amb.charity_jar.slug}?ref={amb.code}",
        "ambassador_code": amb.code,
    }


# ── پردازشگر Outbox انتشار گزارش پیشرفت میدانی برای سهام‌داران (Idea #4) ──────


def _handle_campaign_impact_published(msg: OutboxMessage) -> None:
    """ایجاد اعلان مژده در صندوق پیام تمام خیرینی که در آن حرکت سهم خریده‌اند."""
    campaign_id = str(msg.payload["campaign_id"])
    campaign_slug = str(msg.payload.get("campaign_slug") or "")
    campaign_title = str(msg.payload.get("campaign_title") or "")
    update_title = str(msg.payload.get("title") or "")
    progress = int(msg.payload.get("progress_percent") or 0)

    shareholder_ids = list(
        Contribution.objects.filter(
            campaign_id=campaign_id,
            status=ContributionStatus.PAID,
        )
        .values_list("user_id", flat=True)
        .distinct()
    )
    for uid in shareholder_ids:
        create_user_notification(
            user_id=uid,
            kind=UserNotificationKind.IMPACT_UPDATE,
            title=f"مژده از حرکت «{campaign_title}»: {update_title}",
            body=f"گزارش جدید اجرای میدانی این حرکت با پیشرفت {progress}٪ منتشر شد.",
            action_url=f"/campaigns/{campaign_slug}",
            metadata={"campaign_id": campaign_id, "progress_percent": progress},
        )


# ═══════════════════════════════════════════════════════════════════════════════
# حلقهٔ نجات وجه (Capture Recovery) — داوری خودکار پرداخت‌های رهاشده
# ═══════════════════════════════════════════════════════════════════════════════
#
# مسئله‌ای که این بخش حل می‌کند:
#     کاربر به درگاه می‌رود، پول را می‌دهد، و هرگز برنمی‌گردد. رزرو ۱۵ دقیقه‌ای
#     منقضی می‌شود و سهم به دیگری فروخته می‌شود. تا پیش از این، پرداخت کورکورانه
#     «ناموفق» علامت می‌خورد و آن پول هیچ‌جا — نه در دفترکل، نه در گزارش، نه در
#     هیچ صفی — دیده نمی‌شد.
#
# راه‌حل (سه مسیر، همه در یک تراکنش اتمیک):
#     ۱) درگاه می‌گوید «تأیید نشد»  ⇒ NOT_CAPTURED      (پولی نبوده؛ تمام)
#     ۲) درگاه می‌گوید «تأیید شد» و ظرفیت هست
#                                   ⇒ RECOVERED       (سهم تخصیص + رسید + دفترکل)
#     ۳) درگاه می‌گوید «تأیید شد» و ظرفیت نیست
#                                   ⇒ REFUND_PENDING  (تعهد بازپرداخت + صف ارسال)
# ═══════════════════════════════════════════════════════════════════════════════

_RECOVERY_GRACE_MINUTES = 30
_RECOVERY_MAX_ATTEMPTS = 5


def _recovery_decision_policy() -> dict[str, Any]:
    """خواندن پارامترهای عملیاتی مسیر نجات از سیاست‌های پویا (قابل تغییر بدون دیپلوی)."""
    return {
        "grace_minutes": int(get_policy("recovery.grace_minutes")),
        "max_attempts": int(get_policy("recovery.max_attempts")),
        "auto_refund_enabled": bool(get_policy("recovery.auto_refund_enabled")),
        "auto_refund_max_rial": int(get_policy("recovery.auto_refund_max_rial")),
    }


def _record_recovery_step(
    *,
    recovery: LateCaptureRecovery,
    payment: Payment,
    event_type: str,
    raw_status: str,
    details: dict[str, Any],
) -> None:
    """ثبت ردپای تغییرناپذیر هر گام داوری در ``PaymentEvent`` برای بررسی پس‌رویدادی."""
    PaymentEvent.objects.create(
        payment=payment,
        event_type=event_type,
        raw_status=raw_status[:40],
        details=details,
    )
    recovery.attempt_count = int(recovery.attempt_count) + 1
    recovery.save(update_fields=["attempt_count", "last_error", "updated_at"])


@transaction.atomic
def _recover_captured_payment(
    *,
    payment: Payment,
    contribution: Contribution,
    recovery: LateCaptureRecovery,
    verify_res: Any,
) -> LateCaptureOutcome:
    """تخصیص دوبارهٔ سهم برای پرداختی که پولش در درگاه مانده بود (بدون بازپرداخت)."""
    campaign = (
        Campaign.objects.select_for_update().filter(pk=contribution.campaign_id).first()
        if contribution.campaign_id is not None
        else None
    )
    if campaign is not None and campaign.status != CampaignStatus.ACTIVE:
        # حرکت در این فاصله بسته/تکمیل شده؛ تخصیص خودکار امن نیست.
        return LateCaptureOutcome.REFUND_PENDING

    needed = int(contribution.shares_count)
    available = int(campaign.remaining_shares) if campaign is not None else 0
    recovery.capacity_at_decision = available

    if campaign is not None and needed > available:
        return LateCaptureOutcome.REFUND_PENDING

    now = timezone.now()
    benefactor = Benefactor.objects.select_for_update().get(pk=contribution.benefactor_id)
    target_title = campaign.title if campaign is not None else benefactor.name
    matched_shares = 0
    matched_rial = 0
    applied_grant: MatchingGrant | None = None

    if campaign is not None:
        if is_feature_enabled("feature.matching_grants"):
            grant = (
                MatchingGrant.objects.select_for_update()
                .filter(
                    campaign=campaign,
                    is_active=True,
                    consumed_shares__lt=F("total_pool_shares"),
                )
                .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
                .order_by("created_at")
                .first()
            )
            if grant is not None:
                avail_after = max(
                    0,
                    int(campaign.total_shares)
                    - (int(campaign.paid_shares) + int(contribution.shares_count))
                    - int(campaign.reserved_shares),
                )
                desired = int(contribution.shares_count) * int(grant.match_ratio)
                matched_shares = min(desired, grant.remaining_pool_shares, avail_after)
                if matched_shares > 0:
                    matched_rial = matched_shares * int(campaign.share_price_rial)
                    grant.consumed_shares = int(grant.consumed_shares) + matched_shares
                    grant.save(update_fields=["consumed_shares", "updated_at"])
                    applied_grant = grant

        campaign.paid_shares = int(campaign.paid_shares) + needed
        campaign.matched_shares = int(campaign.matched_shares) + matched_shares
        campaign.collected_online_rial = int(campaign.collected_online_rial) + int(
            contribution.amount_rial
        )
        campaign.matched_amount_rial = int(campaign.matched_amount_rial) + matched_rial
        campaign.supporter_count = int(campaign.supporter_count) + 1
        if (
            campaign.paid_shares + campaign.matched_shares + campaign.external_shares
            >= campaign.total_shares
            and campaign.status == CampaignStatus.ACTIVE
        ):
            campaign.status = CampaignStatus.COMPLETED
            campaign.completed_at = now
        campaign.save(
            update_fields=[
                "paid_shares",
                "matched_shares",
                "collected_online_rial",
                "matched_amount_rial",
                "supporter_count",
                "status",
                "completed_at",
                "updated_at",
            ]
        )
        sync_benefactor_campaign_counters(benefactor_id=benefactor.id)
    else:
        if contribution.charity_jar_id is None:
            return LateCaptureOutcome.MANUAL_REVIEW
        jar = CharityJar.objects.select_for_update().get(pk=contribution.charity_jar_id)
        jar.total_raised_rial = int(jar.total_raised_rial) + int(contribution.amount_rial)
        jar.donor_count = int(jar.donor_count) + 1
        jar.save(update_fields=["total_raised_rial", "donor_count", "updated_at"])

    benefactor.total_raised_rial = (
        int(benefactor.total_raised_rial) + int(contribution.amount_rial) + matched_rial
    )
    benefactor.save(update_fields=["total_raised_rial", "updated_at"])

    # دفترکل: همان ساختار سند وصول، با کلید مرجع متمایز تا با مسیر عادی تعارض نکند.
    ben_code, ben_title, ben_type = benefactor_online_payable_spec(benefactor)
    post_journal_entry(
        reference_key=f"payment.late_captured:{payment.id}",
        kind=JournalEntryKind.CONTRIBUTION_PAID,
        description=f"وصول دیرهنگام مشارکت ({target_title}) — پیگیری {verify_res.ref_id}",
        campaign_id=contribution.campaign_id,
        benefactor_id=benefactor.id,
        actor=None,
        metadata={
            "payment_id": str(payment.id),
            "ref_id": verify_res.ref_id,
            "recovered": True,
            "authority": payment.authority,
        },
        lines=[
            PostingLineSpec(
                account_code=ACC_GATEWAY_RECEIVABLE,
                account_title="دریافتنی درگاه پرداخت آنلاین",
                account_type=LedgerAccountType.ASSET,
                debit_rial=int(contribution.amount_rial),
                memo=f"Authority {payment.authority}",
            ),
            PostingLineSpec(
                account_code=ben_code,
                account_title=ben_title,
                account_type=ben_type,
                credit_rial=int(contribution.amount_rial),
                benefactor_id=benefactor.id,
                memo=f"بازیافت مشارکت {contribution.id}",
            ),
        ],
    )
    if matched_rial > 0 and applied_grant is not None:
        post_journal_entry(
            reference_key=f"payment.late_captured.match:{payment.id}",
            kind=JournalEntryKind.MATCHING_GRANT_APPLIED,
            description=f"اعمال {matched_shares} سهم مضاعف در بازیافت پرداخت {payment.id}",
            campaign_id=contribution.campaign_id,
            benefactor_id=benefactor.id,
            actor=None,
            lines=[
                PostingLineSpec(
                    account_code=ACC_MATCHING_POOL,
                    account_title="حساب تعهد حامیان مضاعف‌کننده",
                    account_type=LedgerAccountType.ASSET,
                    debit_rial=matched_rial,
                    memo=applied_grant.sponsor_name,
                ),
                PostingLineSpec(
                    account_code=ben_code,
                    account_title=ben_title,
                    account_type=ben_type,
                    credit_rial=matched_rial,
                    benefactor_id=benefactor.id,
                ),
            ],
        )

    contribution.status = ContributionStatus.CAPTURED_LATE
    contribution.paid_at = now
    contribution.matched_shares_awarded = matched_shares
    contribution.matched_amount_rial = matched_rial
    contribution.applied_matching_grant = applied_grant
    contribution.save(
        update_fields=[
            "status",
            "paid_at",
            "matched_shares_awarded",
            "matched_amount_rial",
            "applied_matching_grant",
            "updated_at",
        ]
    )

    payment.status = PaymentStatus.VERIFIED
    payment.ref_id = verify_res.ref_id
    payment.card_pan_masked = verify_res.card_pan_masked
    payment.verified_at = now
    payment.save(update_fields=["status", "ref_id", "card_pan_masked", "verified_at", "updated_at"])

    receipt = _issue_signed_receipt(contribution=contribution)

    if contribution.ambassador_link_id is not None:
        AmbassadorLink.objects.filter(pk=contribution.ambassador_link_id).update(
            referred_donors_count=F("referred_donors_count") + 1,
            attributed_shares=F("attributed_shares") + int(contribution.shares_count),
            attributed_amount_rial=F("attributed_amount_rial") + int(contribution.amount_rial),
        )

    create_user_notification(
        user_id=contribution.user_id,
        kind=UserNotificationKind.RECEIPT_READY,
        title="پرداخت شما با تأخیر تأیید شد و مشارکت‌تان ثبت گردید",
        body=(
            f"پرداخت شما در «{target_title}» با کد رهگیری {receipt.verification_code} "
            "ثبت شد. بابت تأخیر پیش‌آمده پوزش می‌خواهیم."
        ),
        action_url=f"/receipts/{receipt.verification_code}",
        metadata={"receipt_number": receipt.receipt_number, "recovered_late": True},
    )
    enqueue_outbox(
        event_type="sms.receipt_issued",
        aggregate_type="DonationReceipt",
        aggregate_id=str(receipt.id),
        payload={
            "phone": contribution.user.phone,
            "campaign_title": target_title,
            "receipt_number": receipt.receipt_number,
        },
    )

    if contribution.campaign_id is not None and is_feature_enabled("feature.merkle_transparency"):
        build_or_refresh_campaign_merkle_snapshot(campaign_id=contribution.campaign_id)

    recovery.outcome = LateCaptureOutcome.RECOVERED
    recovery.decision_reason = "captured_with_available_capacity"
    recovery.gateway_ref_id = verify_res.ref_id
    recovery.recovered_shares = needed
    recovery.resolved_at = now
    record_audit_event(
        action=AuditAction.LATE_CAPTURE_RECOVERED,
        actor=None,
        target_type="Payment",
        target_id=str(payment.id),
        reason="بازیافت خودکار پرداخت پس از انقضای رزرو",
        metadata={
            "contribution_id": str(contribution.id),
            "shares": needed,
            "amount_rial": int(contribution.amount_rial),
            "capacity": available,
        },
    )
    transaction.on_commit(lambda: bump_epoch("campaigns"))
    transaction.on_commit(lambda: bump_epoch("benefactors"))
    transaction.on_commit(lambda: bump_epoch("jars"))
    return LateCaptureOutcome.RECOVERED


@transaction.atomic
def _open_refund_obligation(
    *,
    payment: Payment,
    contribution: Contribution,
    recovery: LateCaptureRecovery,
    verify_res: Any,
    reason: str,
) -> LateCaptureOutcome:
    """ثبت تعهد بازپرداخت برای پولی که گرفته شده ولی سهمی برایش نمانده است.

    نکتهٔ دفترکلی: اینجا **درآمد حذف نمی‌شود** (چون هرگز ثبت نشده بود)؛ بلکه یک
    بدهی صریح «وجه دریافتی که باید بازگردد» در مقابل «دریافتنی از درگاه» ثبت
    می‌شود. یعنی ترازنامه از همان لحظه می‌گوید ما به این حامی بدهکاریم.
    """
    now = timezone.now()
    previous_status = recovery.capacity_at_decision

    payment.status = PaymentStatus.VERIFIED
    payment.ref_id = verify_res.ref_id
    payment.card_pan_masked = verify_res.card_pan_masked
    payment.verified_at = now
    payment.save(update_fields=["status", "ref_id", "card_pan_masked", "verified_at", "updated_at"])

    contribution.status = ContributionStatus.AWAITING_REFUND
    contribution.save(update_fields=["status", "updated_at"])

    refund = PaymentRefund.objects.create(
        payment=payment,
        amount_rial=int(contribution.amount_rial),
        reason=reason[:400],
        refunded_by=None,
        outcome=RefundOutcome.PENDING,
        automation_note="مسیر خودکار بازیافت وجه: سهم در دسترس نبود.",
    )

    post_journal_entry(
        reference_key=f"payment.refund_obligation:{payment.id}",
        kind=JournalEntryKind.CONTRIBUTION_REFUNDED,
        description=f"شناسایی بدهی بازپرداخت وجه حامی بابت {payment.authority}",
        campaign_id=contribution.campaign_id,
        benefactor_id=contribution.benefactor_id,
        actor=None,
        metadata={"payment_id": str(payment.id), "obligation": True},
        lines=[
            PostingLineSpec(
                account_code=ACC_REFUND_LIABILITY,
                account_title="وجه دریافتی که باید به حامی بازگردد",
                account_type=LedgerAccountType.LIABILITY,
                credit_rial=int(contribution.amount_rial),
                memo=f"بازپرداخت معلق {payment.authority}",
            ),
            PostingLineSpec(
                account_code=ACC_GATEWAY_RECEIVABLE,
                account_title="دریافتنی درگاه پرداخت آنلاین",
                account_type=LedgerAccountType.ASSET,
                debit_rial=int(contribution.amount_rial),
                memo=f"Authority {payment.authority}",
            ),
        ],
    )

    recovery.outcome = LateCaptureOutcome.REFUND_PENDING
    recovery.decision_reason = "captured_without_capacity"
    recovery.gateway_ref_id = verify_res.ref_id
    recovery.refund = refund
    recovery.resolved_at = now
    record_audit_event(
        action=AuditAction.REFUND_OBLIGATION_OPENED,
        actor=None,
        target_type="PaymentRefund",
        target_id=str(refund.id),
        reason=reason,
        metadata={
            "payment_id": str(payment.id),
            "contribution_id": str(contribution.id),
            "amount_rial": int(contribution.amount_rial),
            "capacity": previous_status,
        },
    )
    create_user_notification(
        user_id=contribution.user_id,
        kind=UserNotificationKind.REFUND_INITIATED,
        title="مبلغ پرداختی شما در حال بازگشت است",
        body=(
            f"مبلغ {int(contribution.amount_rial):,} ریال که از حساب شما کسر شده بود، "
            "به‌صورت خودکار بازگردانده می‌شود. جایگزین شما از قبل پر شده بود؛ "
            "پوزش ما را پذیرا باشید."
        ),
        action_url="/me/contributions",
        metadata={"payment_id": str(payment.id), "amount_rial": int(contribution.amount_rial)},
    )
    transaction.on_commit(lambda: bump_epoch("campaigns"))
    return LateCaptureOutcome.REFUND_PENDING


@transaction.atomic
def reconcile_one_abandoned_payment(*, payment_id: Any) -> LateCaptureOutcome:
    """داوری کامل یک پرداخت رهاشده؛ idempotent و مطابق ماشین حالت.

    ترتیب کارها:
        ۱) قفل پرداخت و مشارکت (select_for_update) برای جلوگیری از داوری هم‌زمان
        ۲) اگر پیش‌تر داوری شده، همان نتیجه را برگردان (idempotency)
        ۳) از درگاه استعلام بگیر (منبع حقیقت بیرونی، نه حدس ما)
        ۴) بر اساس پاسخ، یکی از سه مسیر را در همان تراکنش اجرا کن
    """
    payment = (
        Payment.objects.select_for_update()
        .select_related("contribution")
        .filter(pk=payment_id)
        .first()
    )
    if payment is None:
        raise NotFoundError("پرداخت مورد نظر یافت نشد.")

    recovery = LateCaptureRecovery.objects.select_for_update().filter(payment=payment).first()
    if recovery is not None and recovery.is_resolved:
        return LateCaptureOutcome(str(recovery.outcome))

    contribution = Contribution.objects.select_for_update().get(pk=payment.contribution_id)
    now = timezone.now()

    if recovery is None:
        recovery = LateCaptureRecovery.objects.create(
            payment=payment,
            contribution=contribution,
            outcome=LateCaptureOutcome.MANUAL_REVIEW,
            capacity_at_decision=(
                int(contribution.campaign.remaining_shares)
                if contribution.campaign_id and contribution.campaign is not None
                else 0
            ),
        )

    policy = _recovery_decision_policy()
    if int(recovery.attempt_count) >= policy["max_attempts"]:
        recovery.outcome = LateCaptureOutcome.MANUAL_REVIEW
        recovery.decision_reason = "max_attempts_exceeded"
        recovery.resolved_at = now
        recovery.save(update_fields=["outcome", "decision_reason", "resolved_at", "updated_at"])
        return LateCaptureOutcome.MANUAL_REVIEW

    # استعلام قطعی از درگاه — تنها منبع حقیقت دربارهٔ اینکه پول گرفته شده یا نه.
    try:
        gw_port = resolve_payment_gateway(payment.gateway_name)
        verify_res = gw_port.verify(
            authority=payment.authority, amount_rial=int(payment.amount_rial)
        )
    except Exception as exc:
        recovery.last_error = f"{type(exc).__name__}: {exc}"[:1000]
        _record_recovery_step(
            recovery=recovery,
            payment=payment,
            event_type="reconcile_error",
            raw_status="NETWORK",
            details={"error": str(exc)[:300]},
        )
        return LateCaptureOutcome.MANUAL_REVIEW

    recovery.gateway_verdict_raw = verify_res.raw_code[:40]

    if not verify_res.verified:
        # درگاه صریحاً می‌گوید تأیید نشده ⇒ پولی نبوده است.
        payment.status = PaymentStatus.FAILED
        payment.save(update_fields=["status", "updated_at"])
        contribution.status = ContributionStatus.EXPIRED
        contribution.save(update_fields=["status", "updated_at"])
        recovery.outcome = LateCaptureOutcome.NOT_CAPTURED
        recovery.decision_reason = f"gateway_declined:{verify_res.raw_code}"
        recovery.resolved_at = now
        recovery.save(
            update_fields=[
                "outcome",
                "decision_reason",
                "gateway_verdict_raw",
                "resolved_at",
                "updated_at",
            ]
        )
        _record_recovery_step(
            recovery=recovery,
            payment=payment,
            event_type="reconcile_not_captured",
            raw_status=verify_res.raw_code,
            details={"verdict": "not_captured"},
        )
        return LateCaptureOutcome.NOT_CAPTURED

    outcome = _recover_captured_payment(
        payment=payment, contribution=contribution, recovery=recovery, verify_res=verify_res
    )
    if outcome == LateCaptureOutcome.REFUND_PENDING:
        outcome = _open_refund_obligation(
            payment=payment,
            contribution=contribution,
            recovery=recovery,
            verify_res=verify_res,
            reason="وجه پس از انقضای رزرو دریافت شد و ظرفیت سهم تکمیل بود.",
        )

    recovery.save()
    LATE_CAPTURE_RECOVERIES_TOTAL.labels(outcome=str(outcome)).inc()
    _record_recovery_step(
        recovery=recovery,
        payment=payment,
        event_type="reconcile_resolved",
        raw_status=verify_res.raw_code,
        details={"outcome": str(outcome)},
    )
    return outcome


def reconcile_abandoned_payments(
    *,
    batch_size: int = 200,
    dry_run: bool = False,
) -> dict[str, Any]:
    """داوری دسته‌ای تمام پرداخت‌های رهاشده — قابل اجرا با Cron هر ۵ دقیقه.

    پارامتر ``grace_period`` (از سیاست ``recovery.grace_minutes``) به درگاه فرصت
    می‌دهد تا وضعیت را نهایی کند و از استعلام‌های زودهنگام و بی‌فایده جلوگیری می‌کند.

    خروجی، آماری است که مستقیماً در پنل سلامت مالی و متریک Prometheus مصرف می‌شود.
    """
    policy = _recovery_decision_policy()
    threshold = timezone.now() - timedelta(minutes=policy["grace_minutes"])

    stats: dict[str, Any] = {
        "scanned": 0,
        "not_captured": 0,
        "recovered": 0,
        "refund_pending": 0,
        "manual_review": 0,
        "error_count": 0,
        "dry_run": dry_run,
    }

    candidates = list(
        Payment.objects.filter(
            status__in=[PaymentStatus.ABANDONED, PaymentStatus.INITIATED],
            created_at__lte=threshold,
            contribution__status__in=[
                ContributionStatus.EXPIRED,
                ContributionStatus.FAILED,
            ],
        )
        .order_by("created_at")
        .values_list("id", flat=True)[:batch_size]
    )
    stats["scanned"] = len(candidates)

    if dry_run:
        stats["candidate_ids"] = [str(c) for c in candidates[:20]]
        return stats

    for payment_id in candidates:
        try:
            outcome = reconcile_one_abandoned_payment(payment_id=payment_id)
        except Exception:
            stats["error_count"] += 1
            continue
        key = str(outcome)
        if key == LateCaptureOutcome.NOT_CAPTURED:
            stats["not_captured"] += 1
        elif key == LateCaptureOutcome.RECOVERED:
            stats["recovered"] += 1
        elif key == LateCaptureOutcome.REFUND_PENDING:
            stats["refund_pending"] += 1
        else:
            stats["manual_review"] += 1

    if stats["recovered"] or stats["refund_pending"]:
        bump_epoch("campaigns")
    return stats


@transaction.atomic
def dispatch_pending_refunds(*, batch_size: int = 100) -> dict[str, int]:
    """ارسال تعهدهای بازپرداخت به درگاه (Cron) با تفکیک صریح «درگاه پشتیبانی نمی‌کند».

    سه نتیجهٔ ممکن برای هر تعهد:
        • درگاه پذیرفت        ⇒ ``SENT`` و انتظار تأیید
        • درگاه پشتیبانی ندارد ⇒ ``MANUAL`` با توضیح روشن (اکانت باید دستی بپردازد)
        • خطای موقت شبکه      ⇒ ``PENDING`` با شمارندهٔ تلاش (تلاش بعدی در اجرای بعد)
    """
    stats = {
        "attempted": 0,
        "sent": 0,
        "manual": 0,
        "failed": 0,
        "skipped": 0,
        "over_cap": 0,
    }
    policy = _recovery_decision_policy()
    if not policy["auto_refund_enabled"]:
        stats["skipped"] = -1
        return stats

    pending = list(
        PaymentRefund.objects.select_for_update(skip_locked=True)
        .filter(outcome=RefundOutcome.PENDING)
        .select_related("payment")
        .order_by("created_at")[:batch_size]
    )

    max_auto_rial = int(policy["auto_refund_max_rial"])

    for refund in pending:
        stats["attempted"] += 1

        # سقف بازپرداخت خودکار: مبالغ بزرگ باید توسط انسان تأیید شوند.
        # این محافظ جلوی «خروج پول بدون چشم انسان» را می‌گیرد.
        if max_auto_rial > 0 and int(refund.amount_rial) > max_auto_rial:
            refund.outcome = RefundOutcome.MANUAL
            refund.automation_note = (
                f"مبلغ {int(refund.amount_rial):,} ریال از سقف بازپرداخت خودکار "
                f"({max_auto_rial:,} ریال) بیشتر است؛ نیازمند تأیید دستی."
            )[:400]
            refund.save(update_fields=["outcome", "automation_note", "updated_at"])
            REFUND_DISPATCH_TOTAL.labels(result="over_cap").inc()
            stats["manual"] += 1
            stats["over_cap"] += 1
            continue

        refund.attempt_count = int(refund.attempt_count) + 1
        refund.last_attempt_at = timezone.now()
        try:
            gw_port = resolve_payment_gateway(refund.payment.gateway_name)
            result = gw_port.refund(
                authority=refund.payment.authority,
                amount_rial=int(refund.amount_rial),
                reason=refund.reason,
            )
        except Exception as exc:
            refund.automation_note = f"خطای ارتباط با درگاه: {type(exc).__name__}"[:400]
            REFUND_DISPATCH_TOTAL.labels(result="error").inc()
            refund.save(
                update_fields=["attempt_count", "last_attempt_at", "automation_note", "updated_at"]
            )
            stats["failed"] += 1
            continue

        if result.unsupported:
            refund.outcome = RefundOutcome.MANUAL
            refund.automation_note = result.message[:400]
            refund.save(
                update_fields=[
                    "outcome",
                    "attempt_count",
                    "last_attempt_at",
                    "automation_note",
                    "updated_at",
                ]
            )
            refund.payment.contribution  # noqa: B018 -- دسترسی برای جلوگیری از غافلگیری N+1
            REFUND_DISPATCH_TOTAL.labels(result="unsupported").inc()
            stats["manual"] += 1
        elif result.accepted:
            refund.outcome = RefundOutcome.SENT
            refund.gateway_reference = result.gateway_reference[:80]
            refund.gateway_raw_code = result.raw_code[:40]
            refund.automation_note = ""
            refund.save(
                update_fields=[
                    "outcome",
                    "gateway_reference",
                    "gateway_raw_code",
                    "attempt_count",
                    "last_attempt_at",
                    "automation_note",
                    "updated_at",
                ]
            )
            REFUND_DISPATCH_TOTAL.labels(result="accepted").inc()
            stats["sent"] += 1
        else:
            refund.gateway_raw_code = result.raw_code[:40]
            refund.automation_note = (result.message or "درگاه بازپرداخت را نپذیرفت.")[:400]
            refund.save(
                update_fields=[
                    "gateway_raw_code",
                    "attempt_count",
                    "last_attempt_at",
                    "automation_note",
                    "updated_at",
                ]
            )
            REFUND_DISPATCH_TOTAL.labels(result="rejected").inc()
            stats["failed"] += 1

    return stats


@transaction.atomic
def settle_refund_obligation(
    *,
    refund_id: Any,
    actor: User | None,
    bank_reference: str = "",
    note: str = "",
    request: Any = None,
) -> PaymentRefund:
    """نهایی‌سازی یک بازپرداخت (تأیید درگاه یا ثبت دستی پرداخت بانکی).

    این همان نقطه‌ای است که حلقه کامل می‌شود: تعهد بدهی صفر می‌شود، سهم‌ها/شمارنده‌ها
    (اگر تخصیص یافته بودند) برگردانده می‌شوند و رسید/اعلان مناسب صادر می‌شود.
    """
    refund = (
        PaymentRefund.objects.select_for_update()
        .select_related("payment")
        .filter(pk=refund_id)
        .first()
    )
    if refund is None:
        raise NotFoundError("درخواست بازپرداخت یافت نشد.")
    if refund.outcome == RefundOutcome.COMPLETED:
        return refund

    payment = Payment.objects.select_for_update().get(pk=refund.payment_id)
    contribution = Contribution.objects.select_for_update().get(pk=payment.contribution_id)
    benefactor = Benefactor.objects.select_for_update().get(pk=contribution.benefactor_id)
    now = timezone.now()

    refund.outcome = RefundOutcome.COMPLETED
    refund.bank_reference = (bank_reference or refund.gateway_reference or refund.bank_reference)[
        :80
    ]
    refund.automation_note = note[:400] or refund.automation_note
    refund.save(update_fields=["outcome", "bank_reference", "automation_note", "updated_at"])

    post_journal_entry(
        reference_key=f"payment.refund_settled:{payment.id}",
        kind=JournalEntryKind.CONTRIBUTION_REFUNDED,
        description=f"تسویه بازپرداخت وجه حامی بابت {payment.authority}",
        campaign_id=contribution.campaign_id,
        benefactor_id=benefactor.id,
        actor=actor,
        metadata={"payment_id": str(payment.id), "refund_id": str(refund.id)},
        lines=[
            PostingLineSpec(
                account_code=ACC_REFUND_LIABILITY,
                account_title="وجه دریافتی که باید به حامی بازگردد",
                account_type=LedgerAccountType.LIABILITY,
                debit_rial=int(refund.amount_rial),
                memo=f"تسویه تعهد {refund.id}",
            ),
            PostingLineSpec(
                account_code=ACC_GATEWAY_RECEIVABLE,
                account_title="دریافتنی درگاه پرداخت آنلاین",
                account_type=LedgerAccountType.ASSET,
                credit_rial=int(refund.amount_rial),
                memo=f"Authority {payment.authority}",
            ),
        ],
    )

    payment.status = PaymentStatus.REFUNDED
    payment.save(update_fields=["status", "updated_at"])
    contribution.status = ContributionStatus.REFUNDED
    contribution.refunded_at = now
    contribution.save(update_fields=["status", "refunded_at", "updated_at"])

    record_audit_event(
        action=AuditAction.REFUND_SETTLED,
        actor=actor,
        target_type="PaymentRefund",
        target_id=str(refund.id),
        reason=note or "تسویه بازپرداخت",
        metadata={
            "payment_id": str(payment.id),
            "amount_rial": int(refund.amount_rial),
            "bank_reference": refund.bank_reference,
        },
        request=request,
    )
    create_user_notification(
        user_id=contribution.user_id,
        kind=UserNotificationKind.REFUND_COMPLETED,
        title="بازپرداخت مبلغ شما انجام شد",
        body=(
            f"مبلغ {int(refund.amount_rial):,} ریال به حساب شما بازگشت. "
            f"مرجع پیگیری: {refund.bank_reference or refund.gateway_reference or refund.id}"
        ),
        action_url="/me/contributions",
        metadata={"refund_id": str(refund.id)},
    )
    transaction.on_commit(lambda: bump_epoch("campaigns"))
    return refund


def register_contribution_outbox_handlers() -> None:
    """اتصال مشترکین صندوق خروجی و آداپتورهای وارونگی وابستگی اپ مشارکت‌ها."""
    from apps.campaigns.selectors import register_short_code_resolver
    from apps.ledger.services import VerifiedPaymentRecord, register_verified_payment_provider

    register_outbox_handler("campaign.impact_published", _handle_campaign_impact_published)
    register_short_code_resolver(lambda sc: try_resolve_and_track_ambassador_code(code=sc))

    def _provide_verified_payments(
        gateway_name: str, period_start: Any, period_end: Any
    ) -> list[VerifiedPaymentRecord]:
        return [
            VerifiedPaymentRecord(
                authority=p.authority,
                ref_id=p.ref_id,
                amount_rial=int(p.amount_rial),
            )
            for p in Payment.objects.filter(
                gateway_name=gateway_name,
                status=PaymentStatus.VERIFIED,
                verified_at__gte=period_start,
                verified_at__lte=period_end,
            )
        ]

    register_verified_payment_provider(_provide_verified_payments)
