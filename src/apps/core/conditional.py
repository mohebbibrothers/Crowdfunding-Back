"""پشتیبانی از درخواست‌های شرطی HTTP (RFC 9111: ETag و پاسخ 304 Not Modified)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from rest_framework.request import Request
from rest_framework.response import Response


def compute_etag(payload: Any, *, version_hint: str = "") -> str:
    """محاسبهٔ ETag قوی و پایدار از بدنهٔ پاسخ و نسخهٔ Epoch."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(f"{version_hint}|{canonical}".encode()).hexdigest()[:24]
    return f'"{digest}"'


def conditional_json_response(
    request: Request,
    payload: Any,
    *,
    version_hint: str = "",
    max_age: int = 0,
) -> Response:
    """برگرداندن پاسخ ``304 Not Modified`` در صورت تطابق ``If-None-Match`` یا بدنهٔ کامل با ``ETag``."""
    etag = compute_etag(payload, version_hint=version_hint)
    cache_control = (
        f"public, max-age={max_age}, must-revalidate"
        if max_age > 0
        else "public, max-age=0, must-revalidate"
    )
    if_none_match = request.META.get("HTTP_IF_NONE_MATCH", "")
    candidates = [token.strip() for token in if_none_match.split(",") if token.strip()]
    if etag in candidates or f"W/{etag}" in candidates:
        resp = Response(status=304)
        resp["ETag"] = etag
        resp["Cache-Control"] = cache_control
        return resp

    resp = Response(payload, status=200)
    resp["ETag"] = etag
    resp["Cache-Control"] = cache_control
    return resp
