"""تنظیمات پایهٔ مشترک سامانه کرادفاندینگ خیرخواهانه (Django 6.1 + MariaDB + Passenger WSGI)."""

from __future__ import annotations

from datetime import timedelta
import json
import os
from pathlib import Path
from typing import Any

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
SRC_DIR = BASE_DIR / "src"


def env_bool(name: str, default: bool = False) -> bool:
    """خواندن متغیر بولی از محیط."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: list[str]) -> list[str]:
    """خواندن فهرست رشته‌ای جداشده با ویرگول از محیط."""
    raw = os.environ.get(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


APP_VERSION = os.environ.get("APP_VERSION", "1.0.0")
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "dev-only-insecure-secret-key-change-in-production-immediately-9876543210",
)
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])

ADMIN_URL_PATH = os.environ.get("DJANGO_ADMIN_URL_PATH", "ops-console/").lstrip("/")
if not ADMIN_URL_PATH.endswith("/"):
    ADMIN_URL_PATH = f"{ADMIN_URL_PATH}/"
ADMIN_ALLOWED_IPS = env_list("DJANGO_ADMIN_ALLOWED_IPS", [])

# کلیدهای رمزنگاری فیلدها، شاخص کور HMAC و لنگر زنجیره ممیزی
FIELD_ENCRYPTION_KEY = os.environ.get("FIELD_ENCRYPTION_KEY", f"enc:{SECRET_KEY}")
PII_BLIND_INDEX_KEY = os.environ.get("PII_BLIND_INDEX_KEY", f"blind:{SECRET_KEY}")
AUDIT_ANCHOR_HMAC_KEY = os.environ.get("AUDIT_ANCHOR_HMAC_KEY", f"anchor:{SECRET_KEY}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # کتابخانه‌های شخص ثالث
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    # کانتکست‌های محدودشده دامنه (۹ ماژول مستقل)
    "apps.core",
    "apps.audit",
    "apps.identity",
    "apps.notifications",
    "apps.benefactors",
    "apps.campaigns",
    "apps.ledger",
    "apps.contributions",
    "apps.reporting",
]

AUTH_USER_MODEL = "identity.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "apps.core.middleware.RequestContextMiddleware",
    "apps.core.middleware.LoadSheddingMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.AdminLoginGuardMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.SecurityAndCacheHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ── پایگاه‌داده MariaDB / MySQL + اتصال مجزای جدول کش اتمیک ──────────────────
DEFAULT_DB_URL = os.environ.get(
    "DATABASE_URL",
    "mysql://crowdfunding:crowdfunding@127.0.0.1:3306/crowdfunding",
)
_primary_db: dict[str, Any] = dict(environ.Env.db_url_config(DEFAULT_DB_URL))
_primary_db["CONN_MAX_AGE"] = 60
_primary_db["CONN_HEALTH_CHECKS"] = True
if "mysql" in str(_primary_db.get("ENGINE", "")):
    _opts = dict(_primary_db.get("OPTIONS") or {})
    _opts.setdefault("charset", "utf8mb4")
    _opts.setdefault(
        "init_command",
        "SET sql_mode='STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'",
    )
    _primary_db["OPTIONS"] = _opts

_cache_db = dict(_primary_db)
_cache_db["CONN_MAX_AGE"] = 0
_cache_db["TEST"] = {"MIRROR": "default"}

DATABASES: dict[str, dict[str, Any]] = {
    "default": _primary_db,
    "cache": _cache_db,
}
DATABASE_ROUTERS = ["apps.core.db.routers.CacheRouter"]

CACHES = {
    "default": {
        "BACKEND": "apps.core.db.cache.AtomicDatabaseCache",
        "LOCATION": "django_cache",
        "TIMEOUT": 300,
        "OPTIONS": {"MAX_ENTRIES": 50_000},
    }
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

LANGUAGE_CODE = "fa-ir"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# محدودیت ابعاد درخواست HTTP (پیشگیری از بارگذاری‌های حجیم غیرمجاز)
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024  # ۲ مگابایت
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# تنظیمات نشست دوگانه (HttpOnly Cookie + SessionAwareJWT)
AUTH_SESSION_COOKIE_NAME = os.environ.get("AUTH_SESSION_COOKIE_NAME", "cf_session")
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    ["http://localhost:3000", "http://127.0.0.1:3000"],
)
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
    ["http://localhost:3000", "http://127.0.0.1:3000"],
)

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.environ.get("JWT_ACCESS_MINUTES", "15"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.environ.get("JWT_REFRESH_DAYS", "30"))),
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

MFA_STEP_UP_TTL_SECONDS = int(os.environ.get("MFA_STEP_UP_TTL_SECONDS", "600"))
EXPOSE_DEV_OTP_CODE = env_bool("EXPOSE_DEV_OTP_CODE", False)
MAX_INFLIGHT_REQUESTS = int(os.environ.get("MAX_INFLIGHT_REQUESTS", "250"))
METRICS_BEARER_TOKEN = os.environ.get("METRICS_BEARER_TOKEN", "")

# تنظیمات پنل پیامک الگومحور (آمادهٔ اتصال با تکمیل متغیرهای محیطی توسط کارفرما)
SMS_ENABLED = env_bool("SMS_ENABLED", False)
SMS_PROVIDER_NAME = os.environ.get("SMS_PROVIDER_NAME", "mock")
SMS_API_URL = os.environ.get("SMS_API_URL", "")
SMS_API_KEY = os.environ.get("SMS_API_KEY", "")
SMS_TIMEOUT_SECONDS = float(os.environ.get("SMS_TIMEOUT_SECONDS", "5.0"))
SMS_PATTERN_CODES: dict[str, str] = json.loads(os.environ.get("SMS_PATTERN_CODES_JSON", "{}"))

# تنظیمات درگاه پرداخت آنلاین (زرین‌پال نسخه ۴ + Sandbox تعاملی)
PUBLIC_APP_BASE_URL = os.environ.get("PUBLIC_APP_BASE_URL", "http://localhost:3000")
PAYMENT_DEFAULT_GATEWAY = os.environ.get("PAYMENT_DEFAULT_GATEWAY", "sandbox")
PAYMENT_CALLBACK_URL = os.environ.get(
    "PAYMENT_CALLBACK_URL",
    "http://localhost:8000/api/v1/payments/callback",
)
ZARINPAL_MERCHANT_ID = os.environ.get("ZARINPAL_MERCHANT_ID", "")

OUTBOUND_ALLOWED_HOSTS = env_list(
    "OUTBOUND_ALLOWED_HOSTS",
    ["payment.zarinpal.com", "sandbox.zarinpal.com", "api.kavenegar.com", "ippanel.com"],
)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.identity.jwt_auth.SessionAwareJWTAuthentication",
        "apps.identity.jwt_auth.SessionAwareCookieAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "EXCEPTION_HANDLER": "apps.core.problems.custom_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "otp_request": os.environ.get("THROTTLE_OTP_REQUEST", "10/min"),
        "otp_verify": os.environ.get("THROTTLE_OTP_VERIFY", "15/min"),
        "mfa_verify": os.environ.get("THROTTLE_MFA_VERIFY", "10/min"),
    },
}

SPECTACULAR_SETTINGS = {
    "OAS_VERSION": "3.1.0",
    "TITLE": "Crowdfunding-Back API — سامانه کرادفاندینگ خیرخواهانه سهم‌محور",
    "DESCRIPTION": (
        "سرویس بک‌اند ماژولار، حسابداری دوطرفه ریالی، شفافیت رمزنگاری درخت مرکل، "
        "مشارکت سریع ۳۰ ثانیه‌ای، نیت‌نامه معنوی، قلک عام، حامی مضاعف و گزارش اکسل ۸ کاربرگه."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/v[0-9]+",
    "ENUM_NAME_OVERRIDES": {
        "CampaignStatusEnum": "apps.campaigns.choices.CampaignStatus.choices",
        "ContributionStatusEnum": "apps.contributions.choices.ContributionStatus.choices",
        "PaymentStatusEnum": "apps.contributions.choices.PaymentStatus.choices",
        "DisbursementStatusEnum": "apps.ledger.choices.DisbursementStatus.choices",
        "ReconciliationItemStatusEnum": "apps.ledger.choices.ReconciliationItemStatus.choices",
        "RiskReviewStatusEnum": "apps.identity.choices.RiskReviewStatus.choices",
        "SmsDeliveryStatusEnum": "apps.notifications.choices.SmsDeliveryStatus.choices",
    },
}

from apps.core.logging import configure_structlog  # noqa: E402

configure_structlog()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
