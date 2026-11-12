"""نگهبان امنیت ارتباطات خروجی (ضد SSRF و الزام HTTPS برای درگاه پرداخت و پیامک)."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def assert_safe_endpoint(url: str, *, allow_http_in_debug: bool = True) -> str:
    """بررسی امن بودن نشانی سرویس بیرونی (الزام HTTPS و مسدودسازی IPهای خصوصی در تولید)."""
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        msg = f"نشانی سرویس بیرونی فاقد دامنهٔ معتبر است: {url}"
        raise ImproperlyConfigured(msg)

    is_dev_or_test = bool(getattr(settings, "DEBUG", False) or getattr(settings, "TESTING", False))
    if scheme != "https" and not (allow_http_in_debug and is_dev_or_test and scheme == "http"):
        msg = f"ارتباط خروجی در محیط تولید فقط با پروتکل HTTPS مجاز است: {url}"
        raise ImproperlyConfigured(msg)

    if not is_dev_or_test:
        try:
            ip_obj = ipaddress.ip_address(hostname)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
                msg = f"اتصال خروجی به آدرس شبکهٔ داخلی در محیط تولید ممنوع است: {hostname}"
                raise ImproperlyConfigured(msg)
        except ValueError:
            if hostname in {"localhost", "localhost.localdomain"}:
                msg = "اتصال خروجی به localhost در محیط تولید ممنوع است."
                raise ImproperlyConfigured(msg) from None

    return url.strip()
