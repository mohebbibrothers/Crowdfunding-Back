"""پشتیبانی رسمی از چرخهٔ منسوخ‌سازی نسخه‌های API منطبق بر استاندارد RFC 8594."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
import logging
from typing import Any, Final

from rest_framework.response import Response

logger = logging.getLogger(__name__)

DEPRECATION_HEADER: Final[str] = "Deprecation"
SUNSET_HEADER: Final[str] = "Sunset"
LINK_HEADER: Final[str] = "Link"


def build_deprecation_headers(
    *,
    sunset_http_date: str = "",
    successor_path: str = "",
    docs_url: str = "",
) -> dict[str, str]:
    """ساخت هدرهای استاندارد RFC 8594 برای اعلام بازنشستگی تدریجی یک مسیر یا نسخه."""
    headers: dict[str, str] = {DEPRECATION_HEADER: "true"}
    if sunset_http_date:
        headers[SUNSET_HEADER] = sunset_http_date
    links: list[str] = []
    if successor_path:
        links.append(f'<{successor_path}>; rel="successor-version"')
    if docs_url:
        links.append(f'<{docs_url}>; rel="deprecation"')
    if links:
        headers[LINK_HEADER] = ", ".join(links)
    return headers


def attach_deprecation_headers(
    response: Response,
    *,
    sunset_http_date: str = "",
    successor_path: str = "",
    docs_url: str = "",
) -> Response:
    """الصاق هدرهای RFC 8594 به یک نمونهٔ ``Response``."""
    for header_name, header_val in build_deprecation_headers(
        sunset_http_date=sunset_http_date,
        successor_path=successor_path,
        docs_url=docs_url,
    ).items():
        response[header_name] = header_val
    return response


def deprecated_endpoint(
    *,
    successor_path: str,
    sunset_http_date: str = "",
    docs_url: str = "",
) -> Callable[[Callable[..., Response]], Callable[..., Response]]:
    """دکوراتور متدهای View برای ثبت لاگ مصرف مسیر قدیمی و درج هدرهای جایگزین."""

    def _decorator(func: Callable[..., Response]) -> Callable[..., Response]:
        @wraps(func)
        def _wrapper(self: Any, request: Any, *args: Any, **kwargs: Any) -> Response:
            logger.warning(
                "deprecated_api_endpoint_called",
                extra={"path": getattr(request, "path", ""), "successor": successor_path},
            )
            resp = func(self, request, *args, **kwargs)
            return attach_deprecation_headers(
                resp,
                sunset_http_date=sunset_http_date,
                successor_path=successor_path,
                docs_url=docs_url,
            )

        return _wrapper

    return _decorator
