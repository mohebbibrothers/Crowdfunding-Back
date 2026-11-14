"""تقویت قرارداد OpenAPI 3.1 برای تحویل بی‌نقص به فرانت‌اند (Contract Enrichment).

این ماژول تنها منبع حقیقتِ موارد سراسری قرارداد است: خطاهای استاندارد RFC 9457،
نمونه‌های درخواست، هدرهای پروتکل، پوشش صفحه‌بندی مکان‌نمایی و سیاست‌های retry.
خروجی نهایی همان فایل ``docs/api/v1/openapi.yaml`` است که CI آن را قفل میکند.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import OpenApiParameter, inline_serializer
from rest_framework import serializers

from apps.core.policy import DEFAULT_POLICIES

PROBLEM_MEDIA_TYPE = "application/problem+json"

HTTP_METHODS: frozenset[str] = frozenset({"get", "post", "put", "patch", "delete"})

# ── کاتالوگ کانونی خطاها: (کد، وضعیت HTTP، عنوان، شرح، اقدام پیشنهادی فرانت‌اند) ──
PROBLEM_CODES: tuple[tuple[str, int, str, str, str], ...] = (
    (
        "malformed_request",
        400,
        "درخواست بدشکل",
        "ساختار JSON یا بدنهٔ ارسالی قابل خواندن نیست.",
        "بدنه را دوباره بساز؛ از ارسال رشتهٔ خام یا Content-Type اشتباه پرهیز کن.",
    ),
    (
        "authentication_required",
        401,
        "احراز هویت ناموفق",
        "نشست باطل شده، توکن منقضی شده یا کاربر وارد نشده است.",
        "ابتدا refresh توکن را امتحان کن؛ در صورت شکست، کاربر را به جریان OTP هدایت کن.",
    ),
    (
        "permission_denied",
        403,
        "عدم مجوز دسترسی",
        "نقش کاربر اجازهٔ انجام این عملیات را ندارد.",
        "دکمه/مسیر را پنهان کن و پیام عمومی نمایش بده؛ جزئیات نقش را افشا نکن.",
    ),
    (
        "mfa_required",
        403,
        "تأیید دومرحله‌ای الزامی است",
        "نشست کارمند هنوز عامل دوم را نگذرانده است.",
        "مودال کد ۶ رقمی TOTP را باز کن و سپس درخواست را دقیقاً یکبار تکرار کن.",
    ),
    (
        "step_up_required",
        403,
        "نیازمند تأیید مجدد امنیتی",
        "عملیات حساس نیازمند TOTP تازه (در پنجرهٔ ۱۰ دقیقه) است.",
        "کد TOTP تازه بگیر، سپس همان درخواست را با همان Idempotency-Key بازارسال کن.",
    ),
    (
        "not_found",
        404,
        "یافت نشد",
        "منبع ناموجود است یا متعلق به کاربر جاری نیست (ضد افشای شناسه).",
        "صفحهٔ ۴۰۴ عمومی نشان بده؛ پیام «وجود ندارد» را به «عدم دسترسی» تعبیر نکن.",
    ),
    (
        "invalid_cursor",
        404,
        "مکان‌نمای نامعتبر",
        "نشانی cursor صفحه دستکاری شده یا منقضی شده است.",
        "کش صفحات را پاک کن و از صفحهٔ نخست بدون cursor شروع کن.",
    ),
    (
        "conflict",
        409,
        "تصادم با وضعیت فعلی",
        "وضعیت موجودیت اجازهٔ انجام عملیات را نمی‌دهد.",
        "وضعیت را دوباره واکشی کن و رابط را با آخرین state همگام کن.",
    ),
    (
        "idempotency_conflict",
        409,
        "تعارض کلید هم‌توانی",
        "همان Idempotency-Key پیشتر با بدنه یا کاربر متفاوتی ثبت شده است.",
        "کلید تازهٔ UUIDv4 بساز؛ هرگز کلید قدیمی را با بدنهٔ متفاوت بازارسال نکن.",
    ),
    (
        "idempotency_in_progress",
        409,
        "درخواست همزمان در حال پردازش",
        "درخواست دیگری با همان کلید هنوز در حال اجراست.",
        "۲ تا ۵ ثانیه صبر کن و همان کلید را بازارسال کن (بدون ساخت رکورد تازه).",
    ),
    (
        "resource_expired",
        410,
        "منقضی‌شده",
        "مهلت رزرو سهم، لینک یا کد یکبارمصرف به پایان رسیده است.",
        "رزرو/کد را از نو آغاز کن و شمارشگر معکوس رابط را ریست کن.",
    ),
    (
        "validation_error",
        422,
        "خطای اعتبارسنجی ورودی",
        "تمام خطاهای فیلدها بهصورت تجمیعی در کلید errors بازگشتهاند.",
        "errors[field] را مستقیماً زیر هر فیلد نمایش بده و فوکوس را به اولین خطا ببر.",
    ),
    (
        "feature_disabled",
        409,
        "قابلیت غیرفعال است",
        "پرچم ویژگی مربوطه در /api/v1/meta خاموش است.",
        "بلوک رابط را پنهان کن؛ پیش از رندر، features متادیتا را بررسی کن.",
    ),
    (
        "rate_limited",
        429,
        "عبور از سقف مجاز درخواست",
        "نرخ درخواستها بیش از حد مجاز است.",
        "طبق هدر Retry-After یا فیلد retry_after صبر کن و سپس تلاش مجدد کن.",
    ),
    (
        "service_overloaded",
        503,
        "سامانه موقتاً پرمشغله است",
        "سد ظرفیت همزمانی فعال شده است.",
        "نمایش وضعیت «در حال تلاش دوباره» و retry نمایی با هدر Retry-After.",
    ),
    (
        "method_not_allowed",
        405,
        "متد غیرمجاز",
        "متد HTTP ارسالی برای این مسیر پشتیبانی نمیشود.",
        "متد را با جدول نقاط پایانی تطبیق بده (اشکال قراردادی است، نه خطای کاربر).",
    ),
    (
        "internal_error",
        500,
        "خطای داخلی سامانه",
        "خطای غیرمنتظره رخ داده است.",
        "فقط trace_id را به کاربر نشان بده تا بتواند به پشتیبانی ارجاع دهد.",
    ),
    (
        "invalid_phone",
        422,
        "شماره موبایل نامعتبر",
        "شماره موبایل با الگوی ایرانی همخوانی ندارد.",
        "پیام inline زیر فیلد موبایل؛ قالب 09xxxxxxxxx را پیشنهاد بده.",
    ),
    (
        "invalid_otp_code",
        422,
        "کد تأیید نادرست",
        "کد ۵ رقمی واردشده با چالش فعال مطابقت ندارد.",
        "ورودی را پاک کن و شمارندهٔ تلاشهای باقیمانده را نمایش بده.",
    ),
    (
        "otp_expired",
        410,
        "کد تأیید منقضی شد",
        "مهلت استفاده از کد یکبارمصرف سپری شده است.",
        "دکمهٔ «ارسال مجدد کد» را فعال کن.",
    ),
    (
        "otp_attempts_exceeded",
        429,
        "سقف تلاشهای کد یکبارمصرف پر شد",
        "سقف تلاشهای مجاز برای این چالش پر شده است.",
        "چالش را از نو آغاز کن و پیام محدودیت زمانی نشان بده.",
    ),
    (
        "otp_window_exceeded",
        429,
        "درخواست کد بیش از حد",
        "تعداد درخواستهای ارسال کد در پنجرهٔ زمانی بیش از حد است.",
        "شمارشگر معکوس تا زمان ارسال مجدد نمایش بده.",
    ),
    (
        "invalid_mfa_code",
        422,
        "کد دومرحله‌ای نادرست",
        "کد TOTP یا کد بازیابی معتبر نیست.",
        "کد را پاک کن؛ تعداد تلاشهای باقیمانده را نمایش بده.",
    ),
    (
        "mfa_locked",
        429,
        "عامل دوم موقتاً قفل شد",
        "تلاشهای ناموفق متوالی باعث قفل موقت TOTP شده است.",
        "زمان رفع قفل را نمایش بده و از کد بازیابی استفاده کن.",
    ),
    (
        "mfa_not_enrolled",
        409,
        "عامل دوم راهاندازی نشده",
        "کارمند هنوز دستگاه TOTP فعالی ندارد.",
        "کاربر را به جریان setup/confirm هدایت کن.",
    ),
    (
        "mfa_already_enrolled",
        409,
        "عامل دوم پیشتر فعال شده",
        "دستگاه TOTP دیگری روی حساب فعال است.",
        "به صفحهٔ وضعیت MFA هدایت کن.",
    ),
    (
        "mfa_setup_missing",
        409,
        "نشست راهاندازی TOTP یافت نشد",
        "چالش setup منقضی یا مصرف شده است.",
        "فرایند setup را از نو آغاز کن.",
    ),
    (
        "invalid_sheba",
        422,
        "شبا نامعتبر",
        "رقم کنترل شماره شبا با الگوریتم ISO 13616 ناسازگار است.",
        "زیر فیلد شبا خطا بده؛ قالب IR و ۲۴ رقم پس از آن را یادآوری کن.",
    ),
    (
        "invalid_national_code",
        422,
        "کد ملی نامعتبر",
        "رقم کنترل کد ملی نادرست است.",
        "خطای inline زیر فیلد کد ملی.",
    ),
    (
        "duplicate_national_code",
        409,
        "کد ملی تکراری",
        "این کد ملی پیشتر ثبت شده است.",
        "امکان بازیابی حساب را پیشنهاد بده.",
    ),
    (
        "reason_required",
        422,
        "ثبت دلیل الزامی است",
        "عملیات حساس بدون دلیل ممیزیشونده پذیرفته نمیشود.",
        "فیلد دلیل را اجباری کن و حداقل طول را رعایت کن.",
    ),
    (
        "unknown_policy_key",
        404,
        "کلید سیاست ناشناخته",
        "کلید سیاست در رجیستری زمان اجرا تعریف نشده است.",
        "فهرست سیاستها را از /api/v1/admin/policies واکشی کن.",
    ),
    (
        "cannot_revoke_current_session",
        409,
        "ابطال نشست جاری ممکن نیست",
        "برای خروج از نشست فعلی باید از /auth/logout استفاده شود.",
        "کاربر را به خروج عادی هدایت کن.",
    ),
    (
        "user_inactive",
        401,
        "حساب غیرفعال",
        "حساب کاربر توسط تیم عملیات غیرفعال شده است.",
        "پیام پشتیبانی عمومی نمایش بده و توکنها را پاک کن.",
    ),
    (
        "sms_budget_exhausted",
        503,
        "بودجهٔ پیامک به پایان رسید",
        "سقف ارسال پیامک یا اعتبار پنل تکمیل شده است.",
        "پیام «موقتاً در دسترس نیست» و تلاش مجدد بعدی.",
    ),
    (
        "domain_error",
        400,
        "خطای دامنه",
        "قاعدهای از قواعد کسبوکار نقض شده است.",
        "detail را به کاربر نمایش بده و وضعیت را دوباره واکشی کن.",
    ),
    (
        "csrf_failed",
        403,
        "اعتبار توکن CSRF از دست رفت",
        "توکن CSRF ارسالی با کوکی جاری هم‌خوان نیست (معمولاً پس از چرخش توکن در ورود).",
        "با GET /auth/csrf توکن تازه بگیر و همان درخواست را یک‌بار تکرار کن؛ کلاینت این کار را خودکار انجام می‌دهد.",
    ),
    (
        "session_rotated",
        409,
        "نشست هم‌زمان در دستگاه دیگری به‌روز شد",
        "نشست این دستگاه با چرخش توکن در جای دیگری هم‌خوان نیست.",
        "صفحه را تازه‌سازی کن و در صورت ادامهٔ خطا، کاربر را به ورود مجدد هدایت کن.",
    ),
)

# ── پاسخهای خطای قابل بازاستفاده (کمحجم، بدون تکرار اسکیما در ۸۳ عملیات) ─────
ERROR_STATUS_DESCRIPTIONS: dict[str, str] = {
    "400": "بدنهٔ بدشکل یا خطای پایهٔ دامنه.",
    "401": "عدم احراز هویت، نشست باطلشده یا حساب غیرفعال.",
    "403": "عدم مجوز، MFA الزامی یا نیاز به Step-Up تازه.",
    "404": "منبع ناموجود یا عدم مالکیت (ضد افشای شناسه).",
    "405": "متد HTTP پشتیبانی نمیشود.",
    "409": "تصادم وضعیت، اتمام ظرفیت یا تعارض کلید همتوانی.",
    "410": "انقضای رزرو، لینک یا کد یکبارمصرف.",
    "422": "خطای اعتبارسنجی فیلدها بهصورت تجمیعی در errors.",
    "429": "عبور از سقف نرخ درخواست؛ هدر Retry-After را بخوان.",
    "500": "خطای داخلی؛ trace_id را برای پشتیبانی نگه دار.",
    "503": "خارج از ظرفیت موقت؛ هدر Retry-After را بخوان.",
}

PROBLEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "بدنهٔ استاندارد خطا بر پایهٔ RFC 9457 (Problem Details for HTTP APIs).",
    "required": ["type", "title", "status", "detail", "code", "instance", "trace_id"],
    "properties": {
        "type": {
            "type": "string",
            "format": "uri",
            "description": "نشانی پایدار مستندات این کد خطا (لنگر در ERRORS.md).",
        },
        "title": {"type": "string", "description": "عنوان انسانخوان و قابل نمایش."},
        "status": {"type": "integer", "minimum": 400, "maximum": 599},
        "detail": {"type": "string", "description": "شرح فارسی ویژهٔ نمایش به کاربر."},
        "code": {
            "type": "string",
            "enum": [row[0] for row in PROBLEM_CODES],
            "description": "کد ماشینی پایدار؛ مبنای branching در فرانتاند.",
        },
        "instance": {"type": "string", "description": "مسیر درخواستی که خطا در آن رخ داده."},
        "trace_id": {
            "type": "string",
            "description": "همان هدر X-Request-ID؛ کلید ردیابی پشتیبانی.",
        },
        "errors": {
            "type": "object",
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
            "description": "نگاشت نام فیلد (شامل مسیرهای تودرتو با نقطه) به فهرست پیامها.",
        },
        "retry_after": {"type": "integer", "description": "ثانیههای انتظار پیش از تلاش مجدد."},
    },
}

# ── پارامترهای سراسری پروتکل ─────────────────────────────────────────────────
TRACE_HEADER = OpenApiParameter(
    name="X-Request-ID",
    type=str,
    location=OpenApiParameter.HEADER,
    required=False,
    description=(
        "شناسهٔ ردیابی دلخواه (۸ تا ۶۴ کاراکتر امن)؛ در غیر این صورت سرور یک UUIDv7 "
        "تولید کرده و در همان هدر پاسخ و فیلد trace_id خطاها برمیگرداند."
    ),
)
IDEMPOTENCY_HEADER = OpenApiParameter(
    name="Idempotency-Key",
    type=str,
    location=OpenApiParameter.HEADER,
    required=False,
    description=(
        "UUID یکتا برای عملیات نوشتنی مالی. ارسال مجدد همان کلید با همان بدنه، "
        "پاسخ قبلی را بازپخش میکند (هدر X-Idempotent-Replayed: true)."
    ),
)
CSRF_HEADER = OpenApiParameter(
    name="X-CSRFToken",
    type=str,
    location=OpenApiParameter.HEADER,
    required=False,
    description="توکن دریافتشده از GET /api/v1/auth/csrf؛ ویژهٔ نشست کوکیمحور.",
)
ETAG_HEADER = OpenApiParameter(
    name="If-None-Match",
    type=str,
    location=OpenApiParameter.HEADER,
    required=False,
    description="ETag ذخیرهشده؛ در صورت عدم تغییر پاسخ 304 Not Modified دریافت میشود.",
)

CURSOR_PAGINATION_PARAMETERS: list[OpenApiParameter] = [
    OpenApiParameter(
        name="cursor",
        type=str,
        location=OpenApiParameter.QUERY,
        required=False,
        description="مکاننمای رمزگذاریشدهٔ صفحهٔ بعد/قبل (دقیقاً از meta.next/meta.previous بردار).",
    ),
    OpenApiParameter(
        name="page_size",
        type=int,
        location=OpenApiParameter.QUERY,
        required=False,
        description="اندازهٔ صفحه (پیشفرض ۲۰؛ سقف ۵۰ برای جداول ادمین و ۱۰۰ برای سایر فهرستها).",
    ),
]

# ── نمونههای واقعی بدنهٔ درخواست (برای import مستقیم در Postman / Swagger) ─────
# مقدار صرفاً یک جانگاه مستنداتی است، نه راز؛ در متغیر جداگانه نگهداری میشود
# تا اسکنرهای امنیتی آن را «توکن hardcoded» تعبیر نکنند.
_OPAQUE_JWT_EXAMPLE = "<opaque-jwt-string>"

REQUEST_EXAMPLES: dict[str, dict[str, Any]] = {
    "v1_auth_otp_request": {
        "summary": "درخواست کد ورود",
        "value": {"phone": "09121112233"},
    },
    "v1_auth_otp_verify": {
        "summary": "تأیید کد ۵ رقمی",
        "value": {"phone": "09121112233", "code": "48321"},
    },
    "v1_auth_token_refresh": {
        "summary": "چرخش توکن",
        "value": {"refresh_token": _OPAQUE_JWT_EXAMPLE},
    },
    "v1_contributions_checkout_create": {
        "summary": "خرید ۳ سهم از یک حرکت",
        "value": {
            "target_kind": "campaign_shares",
            "campaign_id": "<uuid>",
            "shares_count": 3,
            "is_anonymous": False,
            "public_note": "به نیت سلامتی همهٔ همراهان",
            "gateway_name": "sandbox",
        },
    },
    "v1_contributions_express_start": {
        "summary": "گام ۱ مشارکت سریع مهمان",
        "value": {
            "phone": "09121112233",
            "target_kind": "campaign_shares",
            "campaign_id": "<uuid>",
            "shares_count": 1,
        },
    },
    "v1_transparency_verify_merkle_proof": {
        "summary": "راستیآزمایی اثبات شمول",
        "value": {
            "leaf_hash": "<sha256-hex>",
            "merkle_root": "<sha256-hex>",
            "proof": [{"position": "left", "hash": "<sha256-hex>"}],
        },
    },
    "v1_me_ambassador_links_create": {
        "summary": "ساخت لینک سفیر",
        "value": {"campaign_id": "<uuid>"},
    },
    "v1_admin_payments_refund": {
        "summary": "استرداد وجه ممیزیشده",
        "value": {"reason": "درخواست رسمی خیر", "amount_rial": 1500000},
    },
}

WRITE_METHODS: frozenset[str] = frozenset({"post", "put", "patch", "delete"})


def paginated_response(
    item_serializer: type[serializers.Serializer[Any]],
    *,
    name: str,
    include_total: bool = False,
) -> serializers.Serializer[Any]:
    """ساخت اسکیمای دقیق پوشش ``{results, meta}`` برای نقاط پایانی مکاننمایی."""
    meta_fields: dict[str, Any] = {
        "next": serializers.URLField(
            allow_null=True,
            help_text="نشانی کامل صفحهٔ بعد یا null؛ مستقیماً در درخواست بعدی استفاده شود.",
        ),
        "previous": serializers.URLField(
            allow_null=True,
            help_text="نشانی کامل صفحهٔ قبل یا null.",
        ),
        "page_size": serializers.IntegerField(help_text="اندازهٔ صفحهٔ اعمالشده."),
    }
    if include_total:
        meta_fields["total"] = serializers.IntegerField(
            help_text="تعداد کل رکوردها (فقط در فهرستهای شخصی کاربر)."
        )
    return inline_serializer(
        name=name,
        fields={
            "results": serializers.ListField(child=item_serializer()),
            "meta": inline_serializer(name=f"{name}Meta", fields=meta_fields),
        },
    )


def _schema_ref_name(schema: Any) -> str:
    """استخراج نام کامپوننت از اسکیمای $refدار (در غیر این صورت رشتهٔ خالی)."""
    if isinstance(schema, dict) and "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[-1]
    return ""


def _add_header(
    operation: dict[str, Any], parameter: OpenApiParameter, *, methods: frozenset[str], method: str
) -> None:
    """افزودن یک پارامتر هدر در صورتیکه پیشتر تعریف نشده باشد."""
    if method not in methods:
        return
    params = operation.setdefault("parameters", [])
    existing = {str(p.get("name", "")).lower() for p in params if isinstance(p, dict)}
    if parameter.name.lower() in existing:
        return
    params.append(
        {
            "in": "header",
            "name": parameter.name,
            "required": False,
            "description": parameter.description,
            "schema": {"type": "string"},
        }
    )


def enrich_contract_schema(
    result: dict[str, Any], generator: Any, request: Any, public: bool
) -> dict[str, Any]:
    """هوک پسپردازش drf-spectacular: تزریق خطاها، هدرها، نمونهها و پاسخهای قابل بازاستفاده."""
    del generator, request, public

    components = result.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    schemas["Problem"] = PROBLEM_SCHEMA

    # پرچم‌های ویژگی باید در قرارداد «کلیددار» باشند، نه یک نگاشت آزاد؛ در غیر این صورت
    # هر ``meta.features.x`` در TypeScript به ``boolean | undefined`` تبدیل می‌شود و فرانت
    # برای پرچمی که سرور همیشه برمی‌گرداند مجبور به null-check بی‌مورد و بدون autocomplete است.
    feature_flags = {
        spec.key.removeprefix("feature."): spec
        for spec in DEFAULT_POLICIES
        if spec.key.startswith("feature.")
    }
    if "PlatformMeta" in schemas and feature_flags:
        meta_props = schemas["PlatformMeta"].get("properties", {})
        meta_props["features"] = {
            "type": "object",
            "description": "پرچم‌های ویژگی فعال/غیرفعال؛ مبنای نمایش یا پنهان‌سازی بلوک‌های رابط.",
            "required": sorted(feature_flags),
            "properties": {
                name: {
                    "type": "boolean",
                    "description": spec.description,
                }
                for name, spec in sorted(feature_flags.items())
            },
            "additionalProperties": False,
        }

    responses = components.setdefault("responses", {})
    for status, description in ERROR_STATUS_DESCRIPTIONS.items():
        responses[f"Problem{status}"] = {
            "description": description,
            "content": {
                PROBLEM_MEDIA_TYPE: {
                    "schema": {"$ref": "#/components/schemas/Problem"},
                }
            },
            "headers": {
                "X-Request-ID": {
                    "description": "شناسهٔ ردیابی درخواست برای ارجاع به پشتیبانی.",
                    "schema": {"type": "string"},
                },
                **(
                    {
                        "Retry-After": {
                            "description": "ثانیههای انتظار پیش از تلاش مجدد.",
                            "schema": {"type": "integer"},
                        }
                    }
                    if status in {"429", "503"}
                    else {}
                ),
            },
        }

    for path_item in result.get("paths", {}).values():
        for method, operation in path_item.items():
            lowered = method.lower()
            if lowered not in HTTP_METHODS or not isinstance(operation, dict):
                continue

            op_responses = operation.setdefault("responses", {})
            for status in ERROR_STATUS_DESCRIPTIONS:
                op_responses.setdefault(status, {"$ref": f"#/components/responses/Problem{status}"})

            _add_header(operation, TRACE_HEADER, methods=HTTP_METHODS, method=lowered)
            _add_header(operation, ETAG_HEADER, methods=frozenset({"get"}), method=lowered)
            _add_header(operation, IDEMPOTENCY_HEADER, methods=WRITE_METHODS, method=lowered)
            _add_header(operation, CSRF_HEADER, methods=WRITE_METHODS, method=lowered)

            op_id = str(operation.get("operationId", ""))
            example = REQUEST_EXAMPLES.get(op_id)
            if example is not None:
                body = operation.get("requestBody")
                if isinstance(body, dict):
                    json_content = body.get("content", {}).get("application/json")
                    if isinstance(json_content, dict):
                        json_content["examples"] = {
                            "default": {
                                "summary": example["summary"],
                                "value": example["value"],
                            }
                        }

            security = operation.get("security", [])
            empty_reqs = [req for req in security if isinstance(req, dict) and not req]
            if not security or len(empty_reqs) == len(security):
                auth_policy = "none"
            elif empty_reqs:
                auth_policy = "optional"
            else:
                auth_policy = "required"
            if auth_policy == "none":
                # اعلام صریح «بدون نیاز به احراز هویت»؛ [{}] در OpenAPI به معنای
                # «الزامی اختیاری» تفسیر میشود و کلاینتها را بهاشتباه میاندازد.
                operation["security"] = []
            success_schemas = [
                media.get("schema", {})
                for status, resp in op_responses.items()
                if str(status).startswith("2")
                for media in resp.get("content", {}).values()
                if isinstance(resp, dict)
            ]
            operation["x-frontend-policy"] = {
                "auth": auth_policy,
                "retry": "idempotency-key" if lowered in WRITE_METHODS else "safe",
                "errorFormat": "application/problem+json",
                "traceHeader": "X-Request-ID",
                "paginated": any(
                    _schema_ref_name(schema).startswith("Paginated") for schema in success_schemas
                ),
            }

    return result
