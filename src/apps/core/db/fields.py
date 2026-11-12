"""ستون مجازی برای پیاده‌سازی یکتایی شرطی روی MariaDB (جایگزین Partial Unique Index)."""

from __future__ import annotations

from typing import Any

from django.db import models
from django.db.models import Case, F, Q, When


def conditional_key(source: str, condition: Q, output_field: models.Field[Any, Any]) -> Any:
    """تولید ``GeneratedField`` مجازی که فقط هنگام برقراری شرط مقدار دارد و در غیر این صورت NULL است."""
    return models.GeneratedField(
        expression=Case(When(condition, then=F(source)), default=None),
        output_field=output_field,
        db_persist=False,
    )
