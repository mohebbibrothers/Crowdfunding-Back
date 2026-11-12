"""صفحه‌بندی مکان‌نمایی پایدار (Cursor Pagination) بدون هزینهٔ COUNT(*) روی جداول بزرگ."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from rest_framework.exceptions import NotFound
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response

from apps.core.errors import NotFoundError


class StandardCursorPagination(CursorPagination):
    """صفحه‌بندی مکان‌نمایی پیش‌فرض با سقف اندازهٔ صفحه و پاسخ یکپارچهٔ ``{results, meta}``."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
    ordering: str | list[str] | tuple[str, ...] = ("-created_at", "-id")
    include_total: bool = False
    _total_count: int | None = None

    def paginate_queryset(self, queryset: Any, request: Any, view: Any = None) -> list[Any] | None:
        """واکشی صفحه و تبدیل مکان‌نمای دستکاری‌شده به خطای ۴۰۴ استاندارد RFC 9457."""
        if self.include_total:
            self._total_count = int(queryset.count())
        try:
            return super().paginate_queryset(queryset, request, view=view)
        except NotFound as exc:
            raise NotFoundError(
                "نشانی مکان‌نمای صفحه معتبر نیست یا منقضی شده است.",
                code="invalid_cursor",
            ) from exc

    def get_paginated_response(self, data: Any) -> Response:
        """برگرداندن پاسخ در ساختار قراردادی ``{results, meta}``."""
        req = getattr(self, "request", None)
        resolved_size = (self.get_page_size(req) if req is not None else None) or self.page_size
        results = (
            list(data)
            if isinstance(data, Sequence) and not isinstance(data, (str, bytes))
            else data
        )
        meta: dict[str, Any] = {
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "page_size": resolved_size,
        }
        if self.include_total and self._total_count is not None:
            meta["total"] = self._total_count
        return Response({"results": results, "meta": meta})

    def get_paginated_response_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        """تعریف اسکیمای دقیق OpenAPI 3.1 برای پاسخ‌های صفحه‌بندی‌شده."""
        meta_props: dict[str, Any] = {
            "next": {"type": "string", "nullable": True, "format": "uri"},
            "previous": {"type": "string", "nullable": True, "format": "uri"},
            "page_size": {"type": "integer", "example": 20},
        }
        if self.include_total:
            meta_props["total"] = {"type": "integer", "example": 42}
        return {
            "type": "object",
            "required": ["results", "meta"],
            "properties": {
                "results": schema,
                "meta": {
                    "type": "object",
                    "required": ["next", "previous", "page_size"],
                    "properties": meta_props,
                },
            },
        }


class UserListCursorPagination(StandardCursorPagination):
    """صفحه‌بندی فهرست‌های شخصی کاربر که تعداد کل رکوردها (``meta.total``) را نیز برمی‌گرداند."""

    include_total = True


class StaffTableCursorPagination(StandardCursorPagination):
    """صفحه‌بندی میز عملیاتی ادمین بدون ``COUNT(*)`` گران و با سقف ۵۰ ردیف."""

    page_size = 25
    max_page_size = 50
    include_total = False
