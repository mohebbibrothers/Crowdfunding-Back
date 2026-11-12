"""پورت و آداپتورهای درگاه پرداخت (زرین‌پال نسخه ۴ بر حسب ریال + درگاه تعاملی آزمایشی Sandbox)."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
from typing import Protocol

from django.conf import settings
import httpx

from apps.contributions.choices import GatewayName
from apps.core.errors import ValidationError as DomainValidationError
from apps.core.netpin import assert_safe_endpoint


@dataclass(frozen=True, slots=True)
class GatewayInitResult:
    """خروجی آغاز تراکنش در درگاه پرداخت."""

    gateway_name: str
    authority: str
    redirect_url: str


@dataclass(frozen=True, slots=True)
class GatewayVerifyResult:
    """خروجی استعلام تأیید نهایی تراکنش از درگاه پرداخت."""

    verified: bool
    ref_id: str
    card_pan_masked: str = ""
    raw_code: str = ""


class PaymentGatewayPort(Protocol):
    """قرارداد انتزاعی درگاه پرداخت اینترنتی."""

    def initiate(
        self,
        *,
        amount_rial: int,
        callback_url: str,
        description: str,
        mobile: str = "",
    ) -> GatewayInitResult:
        """ایجاد شناسه Authority و نشانی هدایت کاربر به صفحه پرداخت."""

    def verify(self, *, authority: str, amount_rial: int) -> GatewayVerifyResult:
        """استعلام سرور-به-سرور وضعیت پرداخت با مبلغ ریالی دقیق."""


class SandboxGatewayAdapter:
    """درگاه تعاملی Sandbox برای توسعهٔ فرانت‌اند، تست‌های یکپارچه و محیط Staging بدون کلید بانکی."""

    def initiate(
        self,
        *,
        amount_rial: int,
        callback_url: str,
        description: str,
        mobile: str = "",
    ) -> GatewayInitResult:
        del callback_url, description, mobile
        if amount_rial < 10_000:
            raise DomainValidationError("حداقل مبلغ تراکنش شاپرکی ۱۰٬۰۰۰ ریال است.")
        authority = f"SBX-{secrets.token_hex(12).upper()}"
        base_public = str(getattr(settings, "PUBLIC_APP_BASE_URL", "http://localhost:3000")).rstrip(
            "/"
        )
        return GatewayInitResult(
            gateway_name=GatewayName.SANDBOX,
            authority=authority,
            redirect_url=f"{base_public}/payment/sandbox?authority={authority}",
        )

    def verify(self, *, authority: str, amount_rial: int) -> GatewayVerifyResult:
        del amount_rial
        if not authority.startswith("SBX-"):
            return GatewayVerifyResult(verified=False, ref_id="", raw_code="INVALID_AUTHORITY")
        # شماره پیگیری قطعی مشتق‌شده از انتهای Authority برای تکرارپذیری Idempotent
        ref_suffix = authority.replace("SBX-", "")[:12]
        return GatewayVerifyResult(
            verified=True,
            ref_id=f"SBXREF-{ref_suffix}",
            card_pan_masked="6037-99**-****-1234",
            raw_code="100",
        )


class ZarinpalGatewayAdapter:
    """آداپتور رسمی زرین‌پال نسخه ۴ با واحد پولی ریال (``currency = IRR``) و پینینگ HTTPS."""

    def __init__(
        self, *, merchant_id: str, request_url: str, verify_url: str, startpay_base: str
    ) -> None:
        self._merchant_id = merchant_id
        self._request_url = assert_safe_endpoint(request_url)
        self._verify_url = assert_safe_endpoint(verify_url)
        self._startpay_base = assert_safe_endpoint(startpay_base).rstrip("/")

    def initiate(
        self,
        *,
        amount_rial: int,
        callback_url: str,
        description: str,
        mobile: str = "",
    ) -> GatewayInitResult:
        payload: dict[str, object] = {
            "merchant_id": self._merchant_id,
            "amount": int(amount_rial),
            "currency": "IRR",
            "callback_url": callback_url,
            "description": description[:250],
        }
        if mobile:
            payload["metadata"] = {"mobile": mobile}

        with httpx.Client(timeout=8.0) as client:
            resp = client.post(self._request_url, json=payload)
            resp.raise_for_status()
            body = resp.json()

        data = body.get("data") or {}
        code = int(data.get("code") or 0)
        authority = str(data.get("authority") or "")
        if code != 100 or not authority:
            raise DomainValidationError("خطا در دریافت شناسه پرداخت از درگاه زرین‌پال.")

        return GatewayInitResult(
            gateway_name=GatewayName.ZARINPAL,
            authority=authority,
            redirect_url=f"{self._startpay_base}/{authority}",
        )

    def verify(self, *, authority: str, amount_rial: int) -> GatewayVerifyResult:
        payload = {
            "merchant_id": self._merchant_id,
            "amount": int(amount_rial),
            "authority": authority,
        }
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(self._verify_url, json=payload)
            resp.raise_for_status()
            body = resp.json()

        data = body.get("data") or {}
        code = int(data.get("code") or 0)
        if code in {100, 101}:
            return GatewayVerifyResult(
                verified=True,
                ref_id=str(data.get("ref_id") or ""),
                card_pan_masked=str(data.get("card_pan") or ""),
                raw_code=str(code),
            )
        return GatewayVerifyResult(
            verified=False,
            ref_id="",
            raw_code=str(code or "ERR"),
        )


def resolve_payment_gateway(preferred: str | None = None) -> PaymentGatewayPort:
    """انتخاب خودکار آداپتور درگاه بر پایهٔ درخواست و تنظیمات محیطی."""
    default_gw = str(getattr(settings, "PAYMENT_DEFAULT_GATEWAY", GatewayName.SANDBOX))
    chosen = preferred or default_gw
    if chosen == GatewayName.ZARINPAL and bool(getattr(settings, "ZARINPAL_MERCHANT_ID", None)):
        return ZarinpalGatewayAdapter(
            merchant_id=str(settings.ZARINPAL_MERCHANT_ID),
            request_url=str(
                getattr(
                    settings,
                    "ZARINPAL_REQUEST_URL",
                    "https://payment.zarinpal.com/pg/v4/payment/request.json",
                )
            ),
            verify_url=str(
                getattr(
                    settings,
                    "ZARINPAL_VERIFY_URL",
                    "https://payment.zarinpal.com/pg/v4/payment/verify.json",
                )
            ),
            startpay_base=str(
                getattr(
                    settings,
                    "ZARINPAL_STARTPAY_BASE",
                    "https://payment.zarinpal.com/pg/StartPay",
                )
            ),
        )
    return SandboxGatewayAdapter()
