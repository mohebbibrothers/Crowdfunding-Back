"""موتور تعهد کمک مستمر — تولید قسط، یادآوری محترمانه، تسویه و انقضا.

═══════════════════════════════════════════════════════════════════════════════
فلسفهٔ این ماژول

این ماژول **موتور پرداخت نیست**. یک اوریستراتور است: تصمیم می‌گیرد «چه وقت
باید چه چیزی پرداخت شود»، ولی خودِ پرداخت از مسیر موجود عبور می‌کند.

    تعهد  →  قسط  →  یادآوری  →  [خیر روی لینک می‌زند]  →  Contribution عادی
                                                                ↓
                                                    همان دفتر کل، همان رسید

اگر اینجا یک موتور پرداخت جدا می‌ساختیم، دو حقیقت مالی موازی می‌شد و دقیقاً
همان مشکلی را می‌ساختیم که فازهای ۱ و ۳ برای حلش جنگیدند.

سه اصل غیرقابل‌مذاکره:

  ۱. **Idempotency را دیتابیس تضمین می‌کند، نه برنامه.**
     یکتایی ``(pledge, sequence)`` تنها محافظ واقعی در برابر «دو بار کسر از
     حساب خیر» است. منطق برنامه ممکن است با کرش نصفه بماند؛ قید دیتابیس
     نمی‌ماند.

  ۲. **هیچ یادآوری‌ای بیرون از پنجرهٔ محترمانه ارسال نمی‌شود.**
     پیامک ساعت ۳ بامداد = اپلیکیشن اخراج‌شده. این جزئیات کوچک، تفاوت بین
     «ابزار مفید» و «مزاحم» است.

  ۳. **شکست هرگز بی‌صدا نیست.**
     اگر تعهدی منقضی شد، خیر باید خبردار شود. خیر باید بداند که دیگر کمک
     نمی‌کند — نه اینکه فکر کند ماهانه می‌دهد. توقف بی‌صدا بدترین حالت است.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from django.db import transaction
from django.db.models import Count, F, Sum

from apps.contributions.choices import (
    ContributionTargetKind,
    InstallmentStatus,
    PledgeCancelReason,
    PledgeFrequency,
    PledgeStatus,
)
from apps.contributions.models import (
    Contribution,
    PledgeInstallment,
    RecurringPledge,
)
from apps.contributions.scheduling import (
    advance_due_date,
    is_within_reminder_window,
    months_between,
    next_occurrence,
    tehran_day_start_utc,
    tehran_now,
    tehran_today,
)
from apps.core.errors import ConflictError, NotFoundError, ValidationError as DomainValidationError
from apps.core.outbox import enqueue_outbox
from apps.core.policy import get_policy

# ══════════════════════════════════════════════════════════════════════════════
# رجیستری پورت‌ها — جلوگیری از چرخهٔ وابستگی
#
# این ماژول باید «مشارکت» بسازد، ولی ساختار مشارکت در ``services`` است و
# ``services`` به ``identity``/``audit`` و در نهایت ``core`` ارجاع می‌دهد.
# import مستقیم، چرخهٔ واقعی می‌سازد. رجیستری پورت آن را به لبهٔ زمان‌اجرا
# تبدیل می‌کند — همان الگویی که در ``settlement`` آزموده و پذیرفته شد.
# ══════════════════════════════════════════════════════════════════════════════

_CHECKOUT_PROVIDER: Callable[..., Any] | None = None


def register_pledge_checkout_provider(provider: Callable[..., Any]) -> None:
    """ثبت سازندهٔ checkout برای پرداخت یک قسط (توسط ``contributions.apps``)."""
    global _CHECKOUT_PROVIDER  # noqa: PLW0603
    _CHECKOUT_PROVIDER = provider


# ══════════════════════════════════════════════════════════════════════════════
# سیاست‌ها
# ══════════════════════════════════════════════════════════════════════════════


def _pledge_policy() -> dict[str, Any]:
    """خواندن پارامترهای عملیاتی تعهد مستمر از سیاست‌های پویا."""
    return {
        "engine_enabled": bool(get_policy("pledge.engine_enabled")),
        "max_active_per_user": int(get_policy("pledge.max_active_per_user")),
        "min_amount_rial": int(get_policy("pledge.min_amount_rial")),
        "grace_days": int(get_policy("pledge.grace_days")),
        "max_reminders": int(get_policy("pledge.max_reminders_per_installment")),
        "window_start": int(get_policy("pledge.reminder_window_start_hour")),
        "window_end": int(get_policy("pledge.reminder_window_end_hour")),
        "max_consecutive_failures": int(get_policy("pledge.max_consecutive_failures")),
    }


def _interval_for(frequency: str) -> int:
    """تبدیل تناوب به فاصلهٔ ماهانه."""
    return 3 if frequency == PledgeFrequency.QUARTERLY else 1


# ══════════════════════════════════════════════════════════════════════════════
# ۱) ایجاد تعهد
# ══════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class PledgeCreationResult:
    """نتیجهٔ ایجاد یک تعهد مستمر."""

    pledge: RecurringPledge
    first_installment: PledgeInstallment

    def as_dict(self) -> dict[str, Any]:
        return {
            "pledge_id": str(self.pledge.pk),
            "status": str(self.pledge.status),
            "first_due_date": self.first_installment.due_date.isoformat(),
            "amount_rial": int(self.first_installment.amount_rial),
        }


@transaction.atomic
def create_recurring_pledge(
    *,
    user: Any,
    benefactor: Any,
    target_kind: str,
    amount_rial: int,
    frequency: str = PledgeFrequency.MONTHLY,
    campaign: Any = None,
    charity_jar: Any = None,
    shares_count: int = 0,
    start_day: int | None = None,
) -> PledgeCreationResult:
    """ثبت یک تعهد کمک مستمر و ساختن نخستین قسط.

    قواعد اعتبارسنجی عمداً سخت‌گیرانه‌اند، چون هر نقضی که اینجا پذیرفته شود
    تا پایان عمر تعهد (ماه‌ها) تکرار می‌شود:

      • مبلغ زیر حداقل سیاست ⇒ رد (قسط ۱۰ هزار ریالی، هزینهٔ پیامکش بیشتر از
        خودش است).
      • بیش از سقف تعهد فعال هر خیر ⇒ رد (جلوی اسپم و فشار مالی).
      • مقصد نامعتبر ⇒ رد (حرکت و قلک هم‌زمان، یا هیچ‌کدام).

    """
    policy = _pledge_policy()
    if not policy["engine_enabled"]:
        raise ConflictError(
            "موتور تعهد مستمر در حال حاضر غیرفعال است.", code="pledge_engine_disabled"
        )

    amount = int(amount_rial)
    # توجه: بررسی سقف پایین مبلغ **بعد** از محاسبهٔ سهم‌محور انجام می‌شود.
    # اگر اینجا باشد، فراخوانی که فقط ``shares_count`` می‌دهد با مبلغ ۰ رد
    # می‌شود — در حالی که مبلغ واقعی‌اش چند میلیون ریال است.
    if frequency not in PledgeFrequency.values:
        raise DomainValidationError(
            f"تناوب «{frequency}» پشتیبانی نمی‌شود.", code="pledge_invalid_frequency"
        )

    valid_target = (
        target_kind == ContributionTargetKind.CAMPAIGN_SHARES and campaign is not None
    ) or (target_kind == ContributionTargetKind.CHARITY_JAR and charity_jar is not None)
    if not valid_target:
        raise DomainValidationError(
            "مقصد تعهد نامعتبر است: حرکت سهم‌محور نیازمند حرکت و قلک نیازمند قلک است.",
            code="pledge_invalid_target",
        )

    # ── تعهد سهم‌محور: مبلغ باید مضرب صحیح قیمت سهم باشد ────────────────────
    # چرا این اعتبارسنجی اینجاست و نه در زمان پرداخت؟
    #   مسیر checkout سهم، مبلغ را از ``shares × share_price`` می‌سازد، نه از
    #   مبلغ دلخواه. اگر تعهد مبلغی مثل ۱۵۰٬۰۰۰ ریال روی سهمی ۱۰۰٬۰۰۰ ریالی
    #   ثبت شود، یا باید گرد شود (یعنی دزدی چند هزار ریالی) یا پرداخت شکست
    #   می‌خورد — و شکست ماه‌ها بعد و در بدترین لحظه اتفاق می‌افتد.
    #   پس همین‌جا رد می‌شود، با پیامی که می‌گوید چرا.
    resolved_shares = int(shares_count)
    if target_kind == ContributionTargetKind.CAMPAIGN_SHARES and campaign is not None:
        unit_price = int(getattr(campaign, "share_price_rial", 0) or 0)
        if unit_price <= 0:
            raise DomainValidationError(
                "قیمت سهم این حرکت معتبر نیست.", code="pledge_campaign_price_invalid"
            )
        if resolved_shares > 0:
            # اگر تعداد سهم داده شده، مبلغ از آن محاسبه می‌شود (منبع حقیقت = سهم)
            amount = resolved_shares * unit_price
        else:
            # ترتیب بررسی عمدی است: اول «آیا مبلغ اصلاً کافی است؟»، بعد «آیا
            # مضرب صحیح است؟». وگرنه خیری که ۵٬۰۰۰ ریال می‌فرستد پیام
            # «مضرب نیست» می‌گیرد که گمراه‌کننده است — مشکل واقعی او کم‌بودن
            # مبلغ است، نه بخش‌پذیری‌اش.
            if amount < policy["min_amount_rial"]:
                raise DomainValidationError(
                    f"حداقل مبلغ هر قسط {policy['min_amount_rial']:,} ریال است.",
                    code="pledge_amount_too_low",
                )
            if amount % unit_price != 0:
                raise DomainValidationError(
                    f"مبلغ تعهد سهم‌محور باید مضرب صحیح قیمت هر سهم ({unit_price:,} ریال) باشد.",
                    code="pledge_amount_not_share_multiple",
                )
            resolved_shares = amount // unit_price
            if resolved_shares < 1:
                raise DomainValidationError(
                    "دست‌کم یک سهم برای تعهد لازم است.", code="pledge_zero_shares"
                )

    if amount < policy["min_amount_rial"]:
        raise DomainValidationError(
            f"حداقل مبلغ هر قسط {policy['min_amount_rial']:,} ریال است.",
            code="pledge_amount_too_low",
        )

    active_count = RecurringPledge.objects.filter(
        user=user, status__in=[PledgeStatus.ACTIVE, PledgeStatus.PAUSED]
    ).count()
    if active_count >= policy["max_active_per_user"]:
        raise ConflictError(
            f"حداکثر {policy['max_active_per_user']} تعهد فعال برای هر خیر مجاز است.",
            code="pledge_limit_reached",
        )

    today = tehran_today()
    anchor = int(start_day) if start_day is not None else today.day
    if not 1 <= anchor <= 31:
        raise DomainValidationError(
            "روز شروع باید بین ۱ تا ۳۱ باشد.", code="pledge_invalid_start_day"
        )

    interval = _interval_for(frequency)
    # «پس از دیروز» یعنی اگر امروز خودش روز میخ است، قسط اول همین امروز است.
    # این تنها ترفند لازم است؛ هیچ شرط ویژهٔ دیگری وجود ندارد.
    first_due = next_occurrence(
        anchor_day=anchor, after=today - timedelta(days=1), interval_months=interval
    )

    pledge = RecurringPledge.objects.create(
        user=user,
        benefactor=benefactor,
        target_kind=target_kind,
        campaign=campaign,
        charity_jar=charity_jar,
        amount_rial=amount,
        shares_count=resolved_shares,
        frequency=frequency,
        interval_months=interval,
        anchor_day=anchor,
        status=PledgeStatus.ACTIVE,
        next_due_date=first_due,
    )

    installment = _build_installment(pledge=pledge, sequence=1, due=first_due, policy=policy)
    return PledgeCreationResult(pledge=pledge, first_installment=installment)


def _build_installment(
    *, pledge: RecurringPledge, sequence: int, due: date, policy: dict[str, Any]
) -> PledgeInstallment:
    """ساخت (یا بازگرداندن) قسط با شمارهٔ مشخص — idempotent در سطح دیتابیس.

    چرا ``get_or_create`` و نه ``create``؟
        اگر دو پروسهٔ کرون هم‌زمان اجرا شوند، یکی ``IntegrityError`` می‌خورد
        و به کمک ``get_or_create`` همان رکورد موجود را برمی‌گرداند. بدون این،
        یک استثنا کل چرخه را می‌شکست — و چرخهٔ شکسته یعنی قسط‌های آن ماه
        هرگز ساخته نمی‌شوند.
    """
    grace_until = due + timedelta(days=policy["grace_days"])
    idempotency_key = f"pledge:{pledge.pk}:seq:{sequence}"

    installment, _created = PledgeInstallment.objects.get_or_create(
        pledge=pledge,
        sequence=sequence,
        defaults={
            "due_date": due,
            "grace_until": grace_until,
            "amount_rial": int(pledge.amount_rial),
            "shares_count": int(pledge.shares_count),
            "status": InstallmentStatus.SCHEDULED,
            "idempotency_key": idempotency_key,
        },
    )
    return installment


# ══════════════════════════════════════════════════════════════════════════════
# ۲) چرخهٔ تولید قسط
# ══════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class CycleStats:
    """آمار یک اجرای چرخهٔ تعهد مستمر."""

    scanned: int = 0
    installments_created: int = 0
    pledges_advanced: int = 0
    expired_installments: int = 0
    pledges_expired: int = 0
    paused_resumed: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "installments_created": self.installments_created,
            "pledges_advanced": self.pledges_advanced,
            "expired_installments": self.expired_installments,
            "pledges_expired": self.pledges_expired,
            "paused_resumed": self.paused_resumed,
            "errors": self.errors,
        }


@transaction.atomic
def resume_paused_pledges(*, as_of: date | None = None) -> int:
    """بازگرداندن تعهدهایی که دورهٔ توقفشان تمام شده — خودکار، بدون دخالت اپراتور.

    چرا خودکار؟ خیری که «یک ماه توقف» زده، انتظار ندارد خودش یادش بیفتد که
    دوباره فعال کند. توقف‌ها اگر دستی بازگردانده شوند، برای همیشه خاموش می‌مانند.
    """
    today = as_of or tehran_today()
    due_for_resume = RecurringPledge.objects.filter(
        status=PledgeStatus.PAUSED, pause_until__isnull=False, pause_until__lte=today
    )
    count = 0
    for pledge in due_for_resume.select_for_update(skip_locked=True):
        next_due = next_occurrence(
            anchor_day=pledge.anchor_day,
            after=max(today - timedelta(days=1), pledge.next_due_date - timedelta(days=1)),
            interval_months=pledge.interval_months,
        )
        pledge.status = PledgeStatus.ACTIVE
        pledge.pause_until = None
        pledge.next_due_date = max(next_due, today)
        pledge.save(update_fields=["status", "pause_until", "next_due_date", "updated_at"])
        count += 1
    return count


@transaction.atomic
def materialize_due_installments(*, as_of: date | None = None, batch_size: int = 500) -> CycleStats:
    """ساخت قسط برای تعهدهایی که سررسیدشان رسیده است.

    چرا این گام از ارسال یادآوری جدا است؟
        اگر تولید و ارسال در یک تراکنش باشند، یک خطای پیامک می‌تواند تولید
        قسط را هم برگرداند. جدا بودن یعنی حتی اگر پیامک‌ها نرسند، سامانه
        «می‌داند» چه قسطی باید پرداخت شود و در پنل خیر دیده می‌شود.

    ``select_for_update(skip_locked=True)`` اجازه می‌دهد دو پروسهٔ کرون هم‌زمان
    روی دو زیرمجموعهٔ متفاوت کار کنند، بدون آنکه یکی منتظر دیگری بماند.
    """
    policy = _pledge_policy()
    stats = CycleStats()
    if not policy["engine_enabled"]:
        return stats

    today = as_of or tehran_today()

    candidates = list(
        RecurringPledge.objects.select_for_update(skip_locked=True)
        .filter(status=PledgeStatus.ACTIVE, next_due_date__lte=today)
        .order_by("next_due_date")[:batch_size]
    )
    stats.scanned = len(candidates)

    for pledge in candidates:
        try:
            sequence = PledgeInstallment.objects.filter(pledge=pledge).count() + 1
            before = PledgeInstallment.objects.filter(pledge=pledge).count()
            _build_installment(
                pledge=pledge, sequence=sequence, due=pledge.next_due_date, policy=policy
            )
            after = PledgeInstallment.objects.filter(pledge=pledge).count()
            if after > before:
                stats.installments_created += 1

            pledge.next_due_date = advance_due_date(
                current_due=pledge.next_due_date,
                anchor_day=pledge.anchor_day,
                interval_months=pledge.interval_months,
                from_date=today,
            )
            pledge.save(update_fields=["next_due_date", "updated_at"])
            stats.pledges_advanced += 1
        except Exception:
            stats.errors += 1
            continue

    return stats


# ══════════════════════════════════════════════════════════════════════════════
# ۳) یادآوری محترمانه
# ══════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class ReminderStats:
    """آمار اجرای یادآوری."""

    window_open: bool = True
    candidates: int = 0
    sent: int = 0
    skipped_window: int = 0
    skipped_cap: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "window_open": self.window_open,
            "candidates": self.candidates,
            "sent": self.sent,
            "skipped_window": self.skipped_window,
            "skipped_cap": self.skipped_cap,
        }


@transaction.atomic
def dispatch_pledge_reminders(
    *, now: datetime | None = None, batch_size: int = 300
) -> ReminderStats:
    """ارسال یادآوری قسط‌های سررسیدشده — فقط در پنجرهٔ محترمانه.

    سه محافظ پشت سر هم:
      ۱. **پنجرهٔ ساعتی** — بیرون از ۹ تا ۲۱ تهران، هیچ پیامکی نمی‌رود.
      ۲. **سقف یادآوری** — پس از N بار، سکوت (تکرار بی‌پایان = مزاحمت).
      ۳. **Outbox با dedup_key** — اجرای دوبارهٔ کرون، پیامک دوم نمی‌سازد.

    محافظ سوم مهم‌ترین است: کلید قطعی ``pledge:{id}:seq:{n}:reminder:{k}``
    یعنی حتی اگر این تابع ده بار در یک دقیقه اجرا شود، خیر یک پیامک می‌گیرد.
    """
    policy = _pledge_policy()
    stats = ReminderStats()

    if not policy["engine_enabled"]:
        stats.window_open = False
        return stats

    moment = now or tehran_now()
    if not is_within_reminder_window(
        hour=moment.hour, start_hour=policy["window_start"], end_hour=policy["window_end"]
    ):
        stats.window_open = False
        return stats

    today = moment.date()
    due = list(
        PledgeInstallment.objects.select_for_update(skip_locked=True)
        .filter(
            status__in=[InstallmentStatus.SCHEDULED, InstallmentStatus.REMINDED],
            due_date__lte=today,
            reminder_count__lt=policy["max_reminders"],
        )
        .select_related("pledge", "pledge__user", "pledge__campaign", "pledge__charity_jar")
        .order_by("due_date")[:batch_size]
    )
    stats.candidates = len(due)

    for installment in due:
        pledge = installment.pledge
        if pledge.status != PledgeStatus.ACTIVE:
            continue
        reminder_index = int(installment.reminder_count) + 1
        message = enqueue_outbox(
            event_type="sms.pledge_reminder",
            payload={
                "phone": str(getattr(pledge.user, "phone", "") or ""),
                "amount_rial": int(installment.amount_rial),
                "due_date": installment.due_date.isoformat(),
                "target_title": _target_title(pledge),
                "installment_id": str(installment.pk),
                "pledge_id": str(pledge.pk),
            },
            aggregate_type="pledge_installment",
            aggregate_id=str(installment.pk),
            # کلید قطعی بر پایهٔ **روز**، نه شمارنده.
            # چرا؟ چون شمارنده در هر ارسال یک واحد بالا می‌رود؛ اگر کلید به آن
            # گره بخورد، هر اجرای بعدی کلید تازه‌ای می‌سازد و dedup عملاً بی‌اثر
            # می‌شود — همان باگی که تست ``test_reminder_is_deduplicated_by_outbox_key``
            # گرفت. با تاریخ، معنا دقیق است: «هر قسط، حداکثر یک یادآوری در روز».
            dedup_key=(f"pledge:{pledge.pk}:seq:{installment.sequence}:day:{today.isoformat()}"),
        )
        if message is None:
            # پیش‌تر ساخته شده — ولی شمارنده را هم تکرار نمی‌کنیم.
            continue

        installment.reminder_count = reminder_index
        installment.reminded_at = moment
        if installment.status == InstallmentStatus.SCHEDULED:
            installment.status = InstallmentStatus.REMINDED
        installment.save(update_fields=["reminder_count", "reminded_at", "status", "updated_at"])
        stats.sent += 1

    stats.skipped_cap = PledgeInstallment.objects.filter(
        status__in=[InstallmentStatus.SCHEDULED, InstallmentStatus.REMINDED],
        due_date__lte=today,
        reminder_count__gte=policy["max_reminders"],
    ).count()

    return stats


def _target_title(pledge: RecurringPledge) -> str:
    """عنوان خوانا مقصد قسط — برای جایگزینی در متن پیامک."""
    if pledge.campaign is not None:
        return str(getattr(pledge.campaign, "title", ""))[:40]
    if pledge.charity_jar is not None:
        return str(getattr(pledge.charity_jar, "title", ""))[:40]
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# ۴) انقضای اقساط پرداخت‌نشده
# ══════════════════════════════════════════════════════════════════════════════


@transaction.atomic
def expire_stale_installments(*, as_of: date | None = None) -> CycleStats:
    """علامت‌گذاری اقساطی که مهلتشان گذشته و پرداخت نشده‌اند.

    قاعدهٔ «سه شکست متوالی» اینجا اعمال می‌شود. نکتهٔ مهم: انقضا **بی‌صدا**
    نیست — خیر اعلان می‌گیرد. خیری که فکر می‌کند ماهانه می‌دهد ولی در واقع
    نمی‌دهد، در بدترین وضعیت اطلاعاتی است.
    """
    policy = _pledge_policy()
    stats = CycleStats()
    today = as_of or tehran_today()

    stale = list(
        PledgeInstallment.objects.select_for_update(skip_locked=True)
        .filter(
            status__in=[InstallmentStatus.SCHEDULED, InstallmentStatus.REMINDED],
            grace_until__lt=today,
        )
        .select_related("pledge")[:500]
    )

    # یک تعهد ممکن است چند قسط معوق هم‌زمان داشته باشد. هر سه ردیف با
    # ``select_related`` یک نمونهٔ **جداگانه** از همان تعهد را در دست دارند و
    # همه با مقدار کهنه شروع می‌کنند. اگر با ``pledge.save()`` معمولی جلو
    # برویم، هر ردیف ۰ را به ۱ می‌رساند و در پایان شمارنده ۱ می‌ماند — یعنی
    # تعهدی با ۳ قسط معوق هرگز منقضی نمی‌شود و خیر ماه‌ها بی‌خبر می‌ماند.
    # راه‌حل: افزایش اتمیک در دیتابیس (``F``) و بازخوانی مقدار واقعی.
    expired_pledge_ids: set[Any] = set()

    for installment in stale:
        installment.status = InstallmentStatus.FAILED
        installment.failure_reason = "مهلت پرداخت پس از سررسید بدون اقدام گذشت."
        installment.save(update_fields=["status", "failure_reason", "updated_at"])
        stats.expired_installments += 1

        pledge = installment.pledge
        if pledge.pk in expired_pledge_ids:
            continue
        if pledge.status != PledgeStatus.ACTIVE:
            continue

        RecurringPledge.objects.filter(pk=pledge.pk, status=PledgeStatus.ACTIVE).update(
            consecutive_failures=F("consecutive_failures") + 1
        )
        pledge.refresh_from_db(fields=["status", "consecutive_failures", "user_id", "amount_rial"])
        if pledge.status != PledgeStatus.ACTIVE:
            # همان لحظه توسط اجرای دیگری منقضی شد؛ اعلان دوباره نساز.
            expired_pledge_ids.add(pledge.pk)
            continue

        if int(pledge.consecutive_failures) >= policy["max_consecutive_failures"]:
            RecurringPledge.objects.filter(pk=pledge.pk).update(
                status=PledgeStatus.EXPIRED,
                cancel_reason=PledgeCancelReason.NOT_NEEDED,
                cancelled_at=tehran_now_utc(),
            )
            expired_pledge_ids.add(pledge.pk)
            stats.pledges_expired += 1
            enqueue_outbox(
                event_type="notification.pledge_expired",
                payload={
                    "user_id": str(pledge.user_id),
                    "pledge_id": str(pledge.pk),
                    "amount_rial": int(pledge.amount_rial),
                    "consecutive_failures": int(pledge.consecutive_failures),
                },
                aggregate_type="recurring_pledge",
                aggregate_id=str(pledge.pk),
                dedup_key=f"pledge:{pledge.pk}:expired",
            )

    return stats


def tehran_now_utc() -> datetime:
    """زمان فعلی UTC — برای ذخیره در فیلدهای تاریخ‌زمانی.

    تفکیک صریح: تصمیم‌های تقویمی («امروز چه روزی است») با تاریخ تهران گرفته
    می‌شوند، ولی هر چیزی که در دیتابیس ذخیره می‌شود باید UTC باشد. قاطی‌کردن
    این دو، باگ‌هایی می‌سازد که فقط در ساعت ۰۰:۳۰ بامداد ظاهر می‌شوند.
    """
    from django.utils import timezone as dj_timezone

    return dj_timezone.now()


# ══════════════════════════════════════════════════════════════════════════════
# ۵) تسویه — پیوند پرداخت موفق به قسط
# ══════════════════════════════════════════════════════════════════════════════


@transaction.atomic
def settle_installment_payment(
    *, installment_id: Any, contribution: Contribution
) -> PledgeInstallment:
    """پیوند یک مشارکت پرداخت‌شده به قسط مربوطه و به‌روزرسانی شمارنده‌های تعهد.

    Idempotent: اگر قسط از قبل پرداخت‌شده باشد، همان را برمی‌گرداند. این مهم
    است چون ``verify_payment_callback`` ممکن است چند بار اجرا شود (بازگشت
    کاربر، وب‌هوک، کرون داوری) — و هیچ‌کدام نباید قسط را دو بار بشمارند.
    """
    installment = (
        PledgeInstallment.objects.select_for_update()
        .select_related("pledge")
        .filter(pk=installment_id)
        .first()
    )
    if installment is None:
        raise NotFoundError("قسط تعهد مستمر یافت نشد.")

    if installment.status == InstallmentStatus.PAID:
        return installment

    now = tehran_now_utc()
    installment.status = InstallmentStatus.PAID
    installment.contribution = contribution
    installment.paid_at = now
    installment.save(update_fields=["status", "contribution", "paid_at", "updated_at"])

    pledge = installment.pledge
    pledge.total_paid_rial = int(pledge.total_paid_rial) + int(installment.amount_rial)
    pledge.installments_paid = int(pledge.installments_paid) + 1
    pledge.consecutive_failures = 0
    pledge.last_paid_at = now
    pledge.save(
        update_fields=[
            "total_paid_rial",
            "installments_paid",
            "consecutive_failures",
            "last_paid_at",
            "updated_at",
        ]
    )

    # اقساط معوق دیگر این تعهد را ببند: خیر پرداخت کرد.
    PledgeInstallment.objects.filter(pledge=pledge, status=InstallmentStatus.FAILED).update(
        status=InstallmentStatus.SKIPPED, failure_reason="با پرداخت قسط بعدی جبران شد."
    )

    return installment


# ══════════════════════════════════════════════════════════════════════════════
# ۶) اقدام‌های خیر — توقف، بازگشت، لغو، رد قسط
# ══════════════════════════════════════════════════════════════════════════════


@transaction.atomic
def pause_pledge(*, pledge_id: Any, user: Any, until: date | None = None) -> RecurringPledge:
    """توقف موقت تعهد به خواست خیر.

    ``until`` خالی یعنی «تا اطلاع ثانوی» — تعهد در وضعیت ``PAUSED`` می‌ماند
    تا خیر خودش بازگرداند. اگر تاریخ داده شود، ``resume_paused_pledges`` خودکار
    بازش می‌گرداند.
    """
    pledge = _owned_pledge(pledge_id=pledge_id, user=user)
    if pledge.status not in {PledgeStatus.ACTIVE, PledgeStatus.PAUSED}:
        raise ConflictError(
            "این تعهد در وضعیتی نیست که بتوان توقف کرد.", code="pledge_not_pausable"
        )

    pledge.status = PledgeStatus.PAUSED
    pledge.pause_until = until
    pledge.save(update_fields=["status", "pause_until", "updated_at"])

    # اقساط سررسیدشدهٔ آیندهٔ این تعهد باطل می‌شوند (پرداخت‌نشده‌ها).
    PledgeInstallment.objects.filter(
        pledge=pledge,
        status__in=[InstallmentStatus.SCHEDULED, InstallmentStatus.REMINDED],
    ).update(status=InstallmentStatus.VOIDED, failure_reason="تعهد متوقف شد.")
    return pledge


@transaction.atomic
def resume_pledge(*, pledge_id: Any, user: Any) -> RecurringPledge:
    """بازگرداندن تعهد متوقف به وضعیت فعال."""
    pledge = _owned_pledge(pledge_id=pledge_id, user=user)
    if pledge.status != PledgeStatus.PAUSED:
        raise ConflictError("فقط تعهد متوقف را می‌توان بازگرداند.", code="pledge_not_paused")
    pledge.status = PledgeStatus.ACTIVE
    pledge.pause_until = None
    pledge.next_due_date = max(pledge.next_due_date, tehran_today())
    pledge.save(update_fields=["status", "pause_until", "next_due_date", "updated_at"])
    return pledge


@transaction.atomic
def cancel_pledge(
    *, pledge_id: Any, user: Any, reason: str = PledgeCancelReason.USER_REQUEST
) -> RecurringPledge:
    """لغو دائمی تعهد و باطل‌کردن اقساط باز.

    اقساط ``PAID`` هرگز دست نمی‌خورند: پولی که پرداخت شده، پرداخت شده است.
    باطل‌کردنشان یعنی جعل تاریخ مالی.
    """
    pledge = _owned_pledge(pledge_id=pledge_id, user=user)
    if pledge.status in {PledgeStatus.CANCELLED, PledgeStatus.COMPLETED}:
        return pledge

    pledge.status = PledgeStatus.CANCELLED
    pledge.cancel_reason = reason if reason in PledgeCancelReason.values else "other"
    pledge.cancelled_at = tehran_now_utc()
    pledge.save(update_fields=["status", "cancel_reason", "cancelled_at", "updated_at"])

    PledgeInstallment.objects.filter(
        pledge=pledge,
        status__in=[InstallmentStatus.SCHEDULED, InstallmentStatus.REMINDED],
    ).update(status=InstallmentStatus.VOIDED, failure_reason="تعهد لغو شد.")
    return pledge


@transaction.atomic
def skip_installment(
    *, pledge_id: Any = None, installment_id: Any, user: Any, reason: str = ""
) -> PledgeInstallment:
    """رد یک قسط مشخص — «این ماه پرداخت نمی‌کنم».

    تفاوت مهم با لغو: تعهد زنده می‌ماند. ماه بعد قسط بعدی می‌آید. این همان
    انعطافی است که کمک یک‌باره ندارد و به خیر حس کنترل می‌دهد.
    """
    installment = (
        PledgeInstallment.objects.select_for_update()
        .select_related("pledge")
        .filter(pk=installment_id)
        .first()
    )
    if installment is None:
        raise NotFoundError("قسط تعهد مستمر یافت نشد.")
    if installment.pledge.user_id != getattr(user, "pk", None):
        raise NotFoundError("قسط تعهد مستمر یافت نشد.")
    if pledge_id is not None and str(installment.pledge_id) != str(pledge_id):
        raise NotFoundError("قسط تعهد مستمر یافت نشد.")
    if installment.status == InstallmentStatus.PAID:
        raise ConflictError("قسط پرداخت‌شده را نمی‌توان رد کرد.", code="installment_already_paid")
    if installment.status not in {
        InstallmentStatus.SCHEDULED,
        InstallmentStatus.REMINDED,
    }:
        raise ConflictError(
            "این قسط در وضعیتی نیست که بتوان رد کرد.", code="installment_not_skippable"
        )

    installment.status = InstallmentStatus.SKIPPED
    installment.failure_reason = (reason or "خیر این قسط را رد کرد.")[:200]
    installment.save(update_fields=["status", "failure_reason", "updated_at"])

    pledge = installment.pledge
    pledge.installments_skipped = int(pledge.installments_skipped) + 1
    pledge.consecutive_failures = 0  # رد آگاهانه، «شکست» نیست
    pledge.save(update_fields=["installments_skipped", "consecutive_failures", "updated_at"])
    return installment


@transaction.atomic
def update_pledge(
    *,
    pledge_id: Any,
    user: Any,
    amount_rial: int | None = None,
    frequency: str | None = None,
    start_day: int | None = None,
) -> RecurringPledge:
    """ویرایش تعهد — با قاعده‌ای که از دوبار کسر پول جلوگیری می‌کند.

    تغییر مبلغ یا میخ روز **فقط بر اقساط آینده** اثر می‌گذارد. اقساطی که
    سررسیدشان رسیده اما پرداخت نشده‌اند بازنویسی می‌شوند تا خیر مبلغ قدیمی
    را نبیند؛ اقساط پرداخت‌شده هرگز لمس نمی‌شوند.

    نکتهٔ ظریف: اگر فقط مبلغ عوض شود و میخ روز دست نخورد، نباید سررسید بعدی
    جابه‌جا شود — وگرنه خیری که مبلغش را کم کرده، یک ماه هم عقب می‌افتد و
    این تنبیه ناخواسته است.
    """
    pledge = _owned_pledge(pledge_id=pledge_id, user=user)
    if pledge.status not in {PledgeStatus.ACTIVE, PledgeStatus.PAUSED}:
        raise ConflictError("این تعهد قابل ویرایش نیست.", code="pledge_not_editable")

    policy = _pledge_policy()
    fields: list[str] = []

    if amount_rial is not None:
        new_amount = int(amount_rial)
        if new_amount < policy["min_amount_rial"]:
            raise DomainValidationError(
                f"حداقل مبلغ هر قسط {policy['min_amount_rial']:,} ریال است.",
                code="pledge_amount_too_low",
            )
        pledge.amount_rial = new_amount
        fields.append("amount_rial")

    if frequency is not None and frequency != pledge.frequency:
        if frequency not in PledgeFrequency.values:
            raise DomainValidationError(
                f"تناوب «{frequency}» پشتیبانی نمی‌شود.", code="pledge_invalid_frequency"
            )
        pledge.frequency = frequency
        pledge.interval_months = _interval_for(frequency)
        fields += ["frequency", "interval_months"]

    if start_day is not None:
        anchor = int(start_day)
        if not 1 <= anchor <= 31:
            raise DomainValidationError(
                "روز شروع باید بین ۱ تا ۳۱ باشد.", code="pledge_invalid_start_day"
            )
        pledge.anchor_day = anchor
        pledge.next_due_date = next_occurrence(
            anchor_day=anchor,
            after=tehran_today() - timedelta(days=1),
            interval_months=pledge.interval_months,
        )
        fields += ["anchor_day", "next_due_date"]

    if fields:
        pledge.save(update_fields=[*fields, "updated_at"])

    # اقساط سررسیدشدهٔ پرداخت‌نشده با مبلغ جدید هم‌راستا می‌شوند.
    if amount_rial is not None:
        PledgeInstallment.objects.filter(
            pledge=pledge,
            status__in=[InstallmentStatus.SCHEDULED, InstallmentStatus.REMINDED],
        ).update(amount_rial=pledge.amount_rial)

    return pledge


def get_owned_pledge(*, pledge_id: Any, user: Any) -> RecurringPledge:
    """واکشی تعهد متعلق به کاربر با پیش‌بارگذاری مقصد — برای نماها.

    مالکیت **در همان کوئری** فیلتر می‌شود، نه در پایتون. ۴۰۴ برای تعهد
    دیگران، تا از افشای وجود شناسه جلوگیری شود.
    """
    pledge = (
        RecurringPledge.objects.select_related("campaign", "charity_jar")
        .filter(pk=pledge_id, user=user)
        .first()
    )
    if pledge is None:
        raise NotFoundError("تعهد کمک مستمر یافت نشد.")
    return pledge


def _owned_pledge(*, pledge_id: Any, user: Any) -> RecurringPledge:
    """واکشی تعهد متعلق به همین کاربر — با ۴۰۴ (نه ۴۰۳) برای ضد‌افشای مالکیت."""
    pledge = RecurringPledge.objects.filter(pk=pledge_id).first()
    if pledge is None or pledge.user_id != getattr(user, "pk", None):
        raise NotFoundError("تعهد کمک مستمر یافت نشد.")
    return pledge


# ══════════════════════════════════════════════════════════════════════════════
# ۷) پرداخت قسط — از طریق checkout موجود
# ══════════════════════════════════════════════════════════════════════════════


@transaction.atomic
def pay_installment(
    *, pledge_id: Any = None, installment_id: Any, user: Any, request: Any = None
) -> dict[str, Any]:
    """آغاز پرداخت یک قسط سررسیدشده — با ساختن یک مشارکت عادی.

    این تابع **موتور پرداخت تازه نمی‌سازد**. موتور پرداخت موجود را صدا می‌زند
    و نتیجه را به قسط پیوند می‌دهد. اگر مقدار بازگشتی ``redirect_url`` باشد،
    خیر به همان درگاه همیشگی می‌رود.

    اگر سازندهٔ checkout ثبت نشده باشد (مثلاً در یک تست واحد)، خطای صریح
    می‌دهد — نه ``AttributeError`` مبهم.
    """
    if _CHECKOUT_PROVIDER is None:
        raise NotImplementedError(
            "سازندهٔ checkout ثبت نشده است؛ contributions.apps باید "
            "register_pledge_checkout_provider را صدا بزند."
        )

    installment = (
        PledgeInstallment.objects.select_for_update()
        .select_related("pledge")
        .filter(pk=installment_id)
        .first()
    )
    if installment is None or installment.pledge.user_id != getattr(user, "pk", None):
        raise NotFoundError("قسط تعهد مستمر یافت نشد.")
    # اگر مسیر URL شناسهٔ تعهد را هم دارد، باید با قسط بخواند — وگرنه فرانت
    # می‌تواند قسط تعهد A را از مسیر تعهد B بپردازد و گزارش‌ها گمراه شوند.
    if pledge_id is not None and str(installment.pledge_id) != str(pledge_id):
        raise NotFoundError("قسط تعهد مستمر یافت نشد.")
    if installment.status == InstallmentStatus.PAID:
        raise ConflictError("این قسط پیش‌تر پرداخت شده است.", code="installment_already_paid")
    if not installment.is_open:
        raise ConflictError(
            f"این قسط در وضعیت «{installment.get_status_display()}» قابل پرداخت نیست.",
            code="installment_not_payable",
        )

    pledge = installment.pledge
    if pledge.status not in {PledgeStatus.ACTIVE, PledgeStatus.PAUSED}:
        raise ConflictError("تعهد مبدأ فعال نیست؛ پرداخت قسط مجاز نیست.", code="pledge_not_active")

    result = _CHECKOUT_PROVIDER(
        installment=installment,
        pledge=pledge,
        user=user,
        request=request,
    )
    return dict(result)


@transaction.atomic
def link_installment_to_contribution(*, installment_id: Any, contribution: Contribution) -> None:
    """پیوند «در حال پرداخت» — قسط را به مشارکتی که checkout ساخته وصل می‌کند.

    این هنوز تسویه نیست: قسط ``PAID`` نمی‌شود تا درگاه تأیید کند. تفکیک عمدی
    است — «کاربر به درگاه رفت» با «پول رسید» یکی نیست، و فاز ۳ تماماً دربارهٔ
    همین تفاوت بود.
    """
    installment = PledgeInstallment.objects.filter(pk=installment_id).values("pledge_id").first()
    if installment is None:
        raise NotFoundError("قسط تعهد مستمر یافت نشد.")
    PledgeInstallment.objects.filter(pk=installment_id).update(contribution=contribution)
    Contribution.objects.filter(pk=contribution.pk).update(pledge_id=installment["pledge_id"])


# ══════════════════════════════════════════════════════════════════════════════
# ۸) آمار — عددی که بودجه‌بندی را ممکن می‌کند
# ══════════════════════════════════════════════════════════════════════════════


def build_pledge_stats(*, window_days: int = 90) -> dict[str, Any]:
    """آمار تعهدهای مستمر برای مدیر خیریه.

    «MRR» (درآمد ماهانهٔ تکرارشونده) تنها عددی است که یک خیریه برای بودجه‌بندی
    لازم دارد و تا پیش از این فیچر اصلاً وجود نداشت.

    چرا ``collection_rate`` و ``churn_rate`` هر دو در یک پاسخ؟
        مدیر خیریه باید بداند «چقدر پول از دست رفت» و «چند نفر رفتند» —
        این دو با هم داستان را می‌گویند. یکی بدون دیگری گمراه‌کننده است.
    """
    today = tehran_today()
    window_start = today - timedelta(days=window_days)

    active = RecurringPledge.objects.filter(status=PledgeStatus.ACTIVE)
    paused = RecurringPledge.objects.filter(status=PledgeStatus.PAUSED)
    expired = RecurringPledge.objects.filter(status=PledgeStatus.EXPIRED)
    cancelled = RecurringPledge.objects.filter(status=PledgeStatus.CANCELLED)

    active_amount = active.aggregate(total=Sum("amount_rial"))["total"] or 0
    monthly_interval = (
        active.filter(interval_months=1).aggregate(total=Sum("amount_rial"))["total"] or 0
    )
    quarterly_interval = (
        active.filter(interval_months=3).aggregate(total=Sum("amount_rial"))["total"] or 0
    )
    mrr = int(monthly_interval) + int(int(quarterly_interval) // 3)

    window_installments = PledgeInstallment.objects.filter(due_date__gte=window_start)
    paid_in_window = window_installments.filter(status=InstallmentStatus.PAID).count()
    failed_in_window = window_installments.filter(
        status__in=[InstallmentStatus.FAILED, InstallmentStatus.EXPIRED]
    ).count()
    total_settled = paid_in_window + failed_in_window
    collection_rate = round(paid_in_window / total_settled, 4) if total_settled else 1.0

    churned = (
        RecurringPledge.objects.filter(
            status__in=[PledgeStatus.CANCELLED, PledgeStatus.EXPIRED],
            cancelled_at__gte=tehran_day_start_utc(window_start),
        ).count()
        + cancelled.filter(updated_at__gte=tehran_day_start_utc(window_start)).count()
    )

    lifetime_months = [
        months_between(pledge.created_at.date(), today)
        for pledge in RecurringPledge.objects.filter(
            status__in=[PledgeStatus.CANCELLED, PledgeStatus.EXPIRED]
        ).only("created_at")
    ]
    average_lifetime = (
        round(sum(lifetime_months) / len(lifetime_months), 1) if lifetime_months else 0.0
    )

    failure_reasons = (
        PledgeInstallment.objects.filter(
            status=InstallmentStatus.FAILED, due_date__gte=window_start
        )
        .values("failure_reason")
        .annotate(n=Count("id"))
        .order_by("-n")[:5]
    )

    return {
        "active_pledges": active.count(),
        "paused_pledges": paused.count(),
        "expired_pledges": expired.count(),
        "cancelled_pledges": cancelled.count(),
        "monthly_recurring_revenue_rial": mrr,
        "active_pledge_amount_rial": int(active_amount),
        "collection_rate": collection_rate,
        "paid_installments_window": paid_in_window,
        "failed_installments_window": failed_in_window,
        "churn_window": churned,
        "churn_rate": round(churned / max(active.count() + churned, 1), 4),
        "average_pledge_lifetime_months": average_lifetime,
        "top_failure_reasons": [
            {"reason": row["failure_reason"] or "نامشخص", "count": int(row["n"])}
            for row in failure_reasons
        ],
        "generated_for_window_days": window_days,
    }


def pledge_summary_for_user(*, user: Any) -> dict[str, Any]:
    """خلاصهٔ تعهدهای یک خیر — برای داشبورد «کمک من».

    عمداً ساده: خیر سه عدد می‌خواهد — چقدر داده‌ام، چقدر ماهانه می‌دهم،
    قسط بعدی کِی است.
    """
    pledges = RecurringPledge.objects.filter(user=user).exclude(status=PledgeStatus.CANCELLED)
    active = pledges.filter(status=PledgeStatus.ACTIVE)
    next_due = active.order_by("next_due_date").values_list("next_due_date", flat=True).first()
    return {
        "total_paid_rial": int(pledges.aggregate(total=Sum("total_paid_rial"))["total"] or 0),
        "monthly_commitment_rial": int(
            active.filter(interval_months=1).aggregate(total=Sum("amount_rial"))["total"] or 0
        ),
        "active_count": active.count(),
        "next_due_date": next_due.isoformat() if next_due else None,
    }
