"""موتور Policy-as-Data — مدیریت زمان اجرای تمام ۸ قابلیت خلاقانه، ضرایب چیدمان و سقف‌ها.

هیچ قاعدهٔ کسب‌وکاری که ممکن است به تصمیم کارفرما تغییر کند هاردکد نمی‌شود.
هر تغییر در جدول ``PolicyRule`` با نسخهٔ جدید، ثبت دلیل اجباری و رکورد حسابرسی ذخیره می‌شود.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction

from apps.core.cache import bump_epoch, get_or_set_versioned
from apps.core.choices import PolicyValueType
from apps.core.errors import ValidationError as DomainValidationError
from apps.core.models import PolicyRevision, PolicyRule

POLICY_CACHE_NS = "policy"


@dataclass(frozen=True, slots=True)
class PolicySpec:
    """مشخصات پیش‌فرض و نوع دادهٔ یک سیاست سامانه."""

    key: str
    value_type: str
    default: Any
    description: str


DEFAULT_POLICIES: tuple[PolicySpec, ...] = (
    # ── کلیدهای روشن/خاموش ۸ ایدهٔ خلاقانه و داشبورد انگیزشی ───────────────
    PolicySpec(
        "feature.express_one_step_checkout",
        PolicyValueType.BOOL,
        True,
        "ایدهٔ ۱: مشارکت سریع ۳۰ ثانیه‌ای مهمان با OTP درجا و قفل هم‌زمان سهم",
    ),
    PolicySpec(
        "feature.spiritual_dedications",
        PolicyValueType.BOOL,
        True,
        "ایدهٔ ۲: نیت‌نامه، یادبود درگذشتگان و صدور کارت هدیهٔ معنوی قابل اشتراک",
    ),
    PolicySpec(
        "feature.anonymous_and_live_feed",
        PolicyValueType.BOOL,
        True,
        "ایدهٔ ۳: سوئیچ خیر گمنام و جریان زندهٔ آخرین مشارکت‌ها در صفحهٔ حرکت",
    ),
    PolicySpec(
        "feature.impact_updates",
        PolicyValueType.BOOL,
        True,
        "ایدهٔ ۴: تایم‌لاین گزارش‌های پیشرفت میدانی پس از تأمین مالی و اعلان به خیرین",
    ),
    PolicySpec(
        "feature.merkle_transparency",
        PolicyValueType.BOOL,
        True,
        "ایدهٔ ۵: شفافیت رمزنگاری درخت مرکل و راستی‌آزمایی ریاضی سهم هر خیر",
    ),
    PolicySpec(
        "feature.external_offline_funding",
        PolicyValueType.BOOL,
        True,
        "ایدهٔ ۶: ثبت کمک‌های خارج از سایت (پویش آفلاین خیریه) در سرفصل مجزای دفتر کل",
    ),
    PolicySpec(
        "feature.shortlinks_and_ambassadors",
        PolicyValueType.BOOL,
        True,
        "ایدهٔ ۷: پیوندک کوتاه حرکت‌ها و سامانهٔ سفیران خیر برای سنجش اثر معرفی",
    ),
    PolicySpec(
        "feature.charity_general_jars",
        PolicyValueType.BOOL,
        True,
        "ایدهٔ ۸-الف: امکان فعال‌سازی قلک عام مبلغ دلخواه برای هر خیریه",
    ),
    PolicySpec(
        "feature.matching_grants",
        PolicyValueType.BOOL,
        True,
        "ایدهٔ ۸-ب: حامی مضاعف‌کننده (Matching Grant) برای دوبرابر شدن اثر سهم‌ها",
    ),
    # ── پارامترهای عملیاتی، چیدمان عادلانه و حاکمیت مالی ─────────────────────
    PolicySpec(
        "share.hold_ttl_minutes",
        PolicyValueType.INT,
        15,
        "مدت رزرو موقت سهم هنگام انتقال به درگاه بانکی (دقیقه)",
    ),
    PolicySpec(
        "share.max_active_holds_per_user",
        PolicyValueType.INT,
        3,
        "حداکثر تعداد سفارش‌های رزرو فعال هم‌زمان برای هر کاربر (ضد احتکار سهم)",
    ),
    PolicySpec(
        "share.max_per_checkout",
        PolicyValueType.INT,
        10_000,
        "حداکثر تعداد سهم قابل انتخاب در یک تراکنش واحد",
    ),
    PolicySpec(
        "jar.min_amount_rial",
        PolicyValueType.INT,
        100_000,
        "حداقل مبلغ کمک آزاد به قلک خیریه به ریال (معادل ۱۰ هزار تومان)",
    ),
    PolicySpec(
        "jar.max_amount_rial",
        PolicyValueType.INT,
        2_000_000_000,
        "حداکثر مبلغ کمک آزاد در یک تراکنش قلک به ریال",
    ),
    PolicySpec(
        "ranking.weight_unfunded_ratio",
        PolicyValueType.FLOAT,
        0.60,
        "ضریب اهمیت درصد باقی‌ماندهٔ سهم‌ها در چیدمان عادلانه (Fair-Share v2)",
    ),
    PolicySpec(
        "ranking.weight_urgency",
        PolicyValueType.FLOAT,
        0.25,
        "ضریب اهمیت نشان اضطراری در چیدمان عادلانه",
    ),
    PolicySpec(
        "ranking.weight_deadline_proximity",
        PolicyValueType.FLOAT,
        0.15,
        "ضریب اهمیت نزدیکی به مهلت پایان در چیدمان عادلانه",
    ),
    # ── حلقهٔ نجات وجه (Capture Recovery) ────────────────────────────────────
    PolicySpec(
        "recovery.grace_minutes",
        PolicyValueType.INT,
        30,
        "مهلت استعلام مجدد وضعیت پرداخت‌های رهاشده پیش از داوری نهایی (دقیقه)",
    ),
    PolicySpec(
        "recovery.max_attempts",
        PolicyValueType.INT,
        5,
        "حداکثر تلاش خودکار استعلام یک پرداخت رهاشده پیش از ارجاع به بررسی انسانی",
    ),
    PolicySpec(
        "recovery.auto_refund_enabled",
        PolicyValueType.BOOL,
        True,
        "ارسال خودکار تعهدهای بازپرداخت به درگاه (در صورت پشتیبانی درگاه)",
    ),
    PolicySpec(
        "recovery.auto_refund_max_rial",
        PolicyValueType.INT,
        50_000_000,
        "سقف مبلغ بازپرداخت خودکار (ریال)؛ بالاتر از آن نیازمند تأیید انسانی است",
    ),
    # ── لایهٔ حقیقت وجه (Money Truth Layer) ──────────────────────────────────
    PolicySpec(
        "truth.max_statement_age_hours",
        PolicyValueType.INT,
        48,
        "حداکثر فاصلهٔ مجاز از آخرین ورود صورت‌حساب تسویه؛ پس از آن «چشم مستقل» کور تلقی می‌شود",
    ),
    PolicySpec(
        "truth.auto_heal_enabled",
        PolicyValueType.BOOL,
        True,
        "خوددرمانی خودکار پرداخت‌هایی که صورت‌حساب می‌گوید درگاه پول آن‌ها را گرفته ولی داخلی تأیید نشده‌اند",
    ),
    PolicySpec(
        "truth.auto_heal_max_rial",
        PolicyValueType.INT,
        20_000_000,
        "سقف مبلغ خوددرمانی خودکار (ریال)؛ بالاتر از آن نیازمند تأیید انسانی است",
    ),
    PolicySpec(
        "truth.unresolved_impact_alert_rial",
        PolicyValueType.INT,
        5_000_000,
        "آستانهٔ اثر ریالی مغایرت‌های حل‌نشده که هشدار بحرانی تولید می‌کند",
    ),
    # ── تعهد کمک مستمر (v1.4.0) ────────────────────────────────────────────
    PolicySpec(
        "pledge.engine_enabled",
        PolicyValueType.BOOL,
        True,
        "کلید اصلی موتور تعهد مستمر؛ خاموش‌کردن، تولید قسط و یادآوری را متوقف می‌کند",
    ),
    PolicySpec(
        "pledge.max_active_per_user",
        PolicyValueType.INT,
        5,
        "سقف تعهدهای فعال هر خیر — محافظ در برابر فشار مالی و اسپم",
    ),
    PolicySpec(
        "pledge.min_amount_rial",
        PolicyValueType.INT,
        50_000,
        "حداقل مبلغ هر قسط (ریال)؛ پایین‌تر از این، هزینهٔ پیامک از خود قسط بیشتر است",
    ),
    PolicySpec(
        "pledge.grace_days",
        PolicyValueType.INT,
        7,
        "مهلت پرداخت پس از سررسید (روز) پیش از آنکه قسط «شکست‌خورده» شمرده شود",
    ),
    PolicySpec(
        "pledge.max_reminders_per_installment",
        PolicyValueType.INT,
        2,
        "حداکثر یادآوری برای هر قسط؛ بیشتر از این، مزاحمت است نه یادآوری",
    ),
    PolicySpec(
        "pledge.reminder_window_start_hour",
        PolicyValueType.INT,
        9,
        "آغاز پنجرهٔ مجاز ارسال یادآوری (ساعت تهران)",
    ),
    PolicySpec(
        "pledge.reminder_window_end_hour",
        PolicyValueType.INT,
        21,
        "پایان پنجرهٔ مجاز ارسال یادآوری (ساعت تهران، غیرشامل)",
    ),
    PolicySpec(
        "pledge.max_consecutive_failures",
        PolicyValueType.INT,
        3,
        "پس از این تعداد شکست متوالی، تعهد منقضی می‌شود و خیر اعلان می‌گیرد",
    ),
    PolicySpec(
        "governance.maker_checker_disbursement",
        PolicyValueType.BOOL,
        True,
        "الزام تفکیک ثبت‌کننده و تأییدکننده (چهارچشمی) در دستور تسویه با خیریه",
    ),
    PolicySpec(
        "security.staff_step_up_seconds",
        PolicyValueType.INT,
        600,
        "پنجرهٔ اعتبار تأیید تازهٔ TOTP برای عملیات حساس مدیریتی (ثانیه)",
    ),
)

POLICY_REGISTRY: dict[str, PolicySpec] = {spec.key: spec for spec in DEFAULT_POLICIES}


def get_all_policies() -> dict[str, Any]:
    """خواندن نقشهٔ کامل سیاست‌ها (مقادیر دیتابیس ترکیب‌شده با مقادیر پیش‌فرض)."""

    def _load() -> dict[str, Any]:
        values: dict[str, Any] = {spec.key: spec.default for spec in DEFAULT_POLICIES}
        for row in PolicyRule.objects.all():
            values[row.key] = row.raw_value
        return values

    return get_or_set_versioned(POLICY_CACHE_NS, "global", "all", _load, timeout=300)


def get_policy(key: str) -> Any:
    """خواندن مقدار جاری یک سیاست بر پایهٔ کلید آن."""
    if key not in POLICY_REGISTRY:
        msg = f"کلید سیاست ناشناخته است: {key}"
        raise KeyError(msg)
    return get_all_policies().get(key, POLICY_REGISTRY[key].default)


def is_feature_enabled(feature_key: str) -> bool:
    """بررسی فعال بودن یک قابلیت محصولی در سیاست‌های جاری."""
    full_key = feature_key if feature_key.startswith("feature.") else f"feature.{feature_key}"
    return bool(get_policy(full_key))


def _validate_policy_value(spec: PolicySpec, value: Any) -> Any:
    """اعتبارسنجی نوع دادهٔ مقدار جدید سیاست پیش از ذخیره‌سازی."""
    if spec.value_type == PolicyValueType.BOOL:
        if not isinstance(value, bool):
            raise DomainValidationError(
                "مقدار این سیاست باید بولی (true/false) باشد.",
                errors={"value": ["مقدار بولی معتبر ارسال کنید."]},
            )
        return value
    if spec.value_type == PolicyValueType.INT:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise DomainValidationError(
                "مقدار این سیاست باید عدد صحیح مثبت باشد.",
                errors={"value": ["عدد صحیح مثبت ارسال کنید."]},
            )
        return value
    if spec.value_type == PolicyValueType.FLOAT:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 0:
            raise DomainValidationError(
                "مقدار این سیاست باید عدد نامنفی باشد.",
                errors={"value": ["عدد نامنفی معتبر ارسال کنید."]},
            )
        return float(value)
    if spec.value_type == PolicyValueType.STRING:
        if not isinstance(value, str):
            raise DomainValidationError(
                "مقدار این سیاست باید رشته باشد.",
                errors={"value": ["رشتهٔ متنی معتبر ارسال کنید."]},
            )
        return value
    return value


def set_policy_value(
    *,
    key: str,
    value: Any,
    reason: str,
    actor_id: UUID | None,
) -> PolicyRule:
    """تغییر نسخه‌دار یک سیاست همراه با ثبت دلیل اجباری و ابطال فوری کش."""
    spec = POLICY_REGISTRY.get(key)
    if spec is None:
        raise DomainValidationError(
            f"سیاست «{key}» در رجیستری سامانه تعریف نشده است.",
            code="unknown_policy_key",
            errors={"key": ["کلید سیاست معتبر نیست."]},
        )
    cleaned_reason = reason.strip()
    if len(cleaned_reason) < 5:
        raise DomainValidationError(
            "ثبت دلیل روشن (حداقل ۵ نویسه) برای تغییر سیاست‌های سامانه الزامی است.",
            code="reason_required",
            errors={"reason": ["دلیل تغییر سیاست را کامل وارد کنید."]},
        )
    validated = _validate_policy_value(spec, value)

    with transaction.atomic():
        existing = PolicyRule.objects.select_for_update().filter(key=key).first()
        if existing is None:
            rule = PolicyRule.objects.create(
                key=key,
                value_type=spec.value_type,
                raw_value=validated,
                description=spec.description,
                version=1,
                updated_by_id=actor_id,
            )
            previous_val: Any = spec.default
        else:
            previous_val = existing.raw_value
            existing.version += 1
            existing.raw_value = validated
            existing.updated_by_id = actor_id
            existing.save(update_fields=["raw_value", "version", "updated_by_id", "updated_at"])
            rule = existing

        PolicyRevision.objects.create(
            policy=rule,
            version=rule.version,
            previous_value=previous_val,
            new_value=validated,
            reason=cleaned_reason,
            changed_by_id=actor_id,
        )

    bump_epoch(POLICY_CACHE_NS, "global")
    return rule
