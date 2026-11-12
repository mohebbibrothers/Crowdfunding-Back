"""پورت انتزاعی و آداپتورهای ارسال پیامک الگومحور (آمادهٔ اتصال آنی به پنل پیامکی کارفرما)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
import httpx

from apps.core.netpin import assert_safe_endpoint


@dataclass(frozen=True, slots=True)
class SmsDispatchResult:
    """نتیجهٔ ارسال یک پیامک الگومحور توسط آداپتور."""

    provider_name: str
    delivered: bool
    mocked: bool
    message_id: str = ""


class SmsProviderPort(Protocol):
    """قرارداد پورت ارسال پیامک الگومحور (Hexagonal Port)."""

    def send_pattern(
        self,
        *,
        phone: str,
        pattern_key: str,
        tokens: dict[str, str],
    ) -> SmsDispatchResult:
        """ارسال پیامک بر پایهٔ کد الگوی مصوب بدون متن آزاد."""


class MockSmsAdapter:
    """آداپتور آزمایشی بدون فراخوانی شبکه (فعال پیش‌فرض تا زمان ثبت کلید پنل پیامک واقعی)."""

    def send_pattern(
        self,
        *,
        phone: str,
        pattern_key: str,
        tokens: dict[str, str],
    ) -> SmsDispatchResult:
        """ثبت تحویل مجازی بدون تماس با شبکهٔ بیرونی."""
        del phone, pattern_key, tokens
        return SmsDispatchResult(
            provider_name="mock",
            delivered=True,
            mocked=True,
            message_id="mock-ok",
        )


class HttpPatternSmsAdapter:
    """آداپتور عمومی REST برای پنل‌های پیامک الگومحور ایرانی (کاوه‌نگار، ایران‌پیامک، ملی‌پیامک، فراز)."""

    def __init__(
        self,
        *,
        provider_name: str,
        endpoint_url: str,
        api_key: str,
        pattern_map: dict[str, str],
        timeout_seconds: float = 5.0,
    ) -> None:
        self._provider_name = provider_name
        self._endpoint_url = assert_safe_endpoint(endpoint_url)
        self._api_key = api_key
        self._pattern_map = pattern_map
        self._timeout = timeout_seconds

    def send_pattern(
        self,
        *,
        phone: str,
        pattern_key: str,
        tokens: dict[str, str],
    ) -> SmsDispatchResult:
        """فراخوانی HTTPS امن سرویس پیامک با کد الگوی نگاشت‌شده."""
        remote_pattern = self._pattern_map.get(pattern_key, pattern_key)
        payload = {
            "receptor": phone,
            "pattern_code": remote_pattern,
            "values": tokens,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Api-Key": self._api_key,
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(self._endpoint_url, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json() if resp.content else {}
        msg_id = str(body.get("message_id") or body.get("id") or "sent")
        return SmsDispatchResult(
            provider_name=self._provider_name,
            delivered=True,
            mocked=False,
            message_id=msg_id[:100],
        )


def resolve_sms_provider() -> SmsProviderPort:
    """انتخاب خودکار آداپتور پیامک از روی متغیرهای محیطی."""
    if not getattr(settings, "SMS_ENABLED", False):
        return MockSmsAdapter()
    return HttpPatternSmsAdapter(
        provider_name=str(getattr(settings, "SMS_PROVIDER_NAME", "iranpayamak")),
        endpoint_url=str(getattr(settings, "SMS_API_URL", "")),
        api_key=str(getattr(settings, "SMS_API_KEY", "")),
        pattern_map=dict(getattr(settings, "SMS_PATTERN_CODES", {})),
        timeout_seconds=float(getattr(settings, "SMS_TIMEOUT_SECONDS", 5.0)),
    )
