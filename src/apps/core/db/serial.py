"""قفل تراکنشی نام‌دار بدون بن‌بست برای سریال‌سازی زنجیرهٔ حسابرسی و شماره‌های ترتیبی."""

from __future__ import annotations

from django.db import DEFAULT_DB_ALIAS, connections, models
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from apps.core.models import SerialLock

MAX_LOCK_NAME_LENGTH = 64


def quoted_column(connection: BaseDatabaseWrapper, model: type[models.Model], name: str) -> str:
    """بازگرداندن نام نقل‌شدهٔ ستون پایگاه‌داده برای یک فیلد مدل."""
    field = model._meta.get_field(name)
    if not isinstance(field, models.Field) or not field.column:
        msg = f"فیلد «{name}» دارای ستون دیتابیسی نیست."
        raise TypeError(msg)
    return str(connection.ops.quote_name(field.column))


def serialize_on(name: str, *, using: str = DEFAULT_DB_ALIAS) -> None:
    """اخذ قفل انحصاری ردیفی روی نام مشخص تا زمان commit یا rollback تراکنش جاری."""
    if not name or len(name) > MAX_LOCK_NAME_LENGTH:
        msg = f"نام قفل باید بین ۱ تا {MAX_LOCK_NAME_LENGTH} نویسه باشد."
        raise ValueError(msg)
    connection = connections[using]
    if not connection.in_atomic_block:
        msg = "فراخوانی serialize_on فقط درون transaction.atomic مجاز است."
        raise TransactionManagementError(msg)

    table = connection.ops.quote_name(SerialLock._meta.db_table)
    column = quoted_column(connection, SerialLock, "name")
    created_col = quoted_column(connection, SerialLock, "created_at")
    now = timezone.now()
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "mysql":
            sql = (
                f"INSERT INTO {table} ({column}, {created_col}) VALUES (%s, %s) "  # noqa: S608  # nosec B608
                f"ON DUPLICATE KEY UPDATE {column} = {column}"
            )
            cursor.execute(sql, [name, now])
        elif vendor == "postgresql":
            sql = (
                f"INSERT INTO {table} ({column}, {created_col}) VALUES (%s, %s) "  # noqa: S608  # nosec B608
                f"ON CONFLICT ({column}) DO UPDATE SET {column} = EXCLUDED.{column}"
            )
            cursor.execute(sql, [name, now])
        else:
            SerialLock.objects.using(using).get_or_create(name=name)
            list(SerialLock.objects.using(using).select_for_update().filter(name=name))
