"""کش پایگاه‌داده با ``incr`` و ``decr`` اتمیک زیر قفل ردیفی (جایگزین بومی Redis روی cPanel)."""

from __future__ import annotations

import base64
from datetime import datetime
import pickle  # nosec B403
from typing import Any

from django.core.cache.backends.db import DatabaseCache
from django.db import connections, models, router, transaction
from django.utils.timezone import now as tz_now


class AtomicDatabaseCache(DatabaseCache):
    """نسخهٔ بدون مسابقهٔ ``DatabaseCache`` جنگو با قفل ``SELECT ... FOR UPDATE``."""

    _table: str

    def incr(self, key: Any, delta: int = 1, version: int | None = None) -> int:
        """افزایش اتمیک مقدار کلید؛ در صورت نبود یا انقضای کلید ``ValueError`` صادر می‌شود."""
        cache_key = self.make_and_validate_key(key, version=version)
        db = router.db_for_write(self.cache_model_class)
        connection = connections[db]
        quote = connection.ops.quote_name
        table = quote(self._table)
        expression = models.Expression(output_field=models.DateTimeField())
        converters = connection.ops.get_db_converters(expression) + expression.get_db_converters(
            connection
        )
        for_update = " FOR UPDATE" if connection.features.has_select_for_update else ""

        with transaction.atomic(using=db), connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {quote('value')}, {quote('expires')} FROM {table} "  # noqa: S608  # nosec B608
                f"WHERE {quote('cache_key')} = %s{for_update}",
                [cache_key],
            )
            row = cursor.fetchone()
            if row is None:
                msg = f"Key '{key}' not found"
                raise ValueError(msg)
            raw_value, expires = row
            for converter in converters:
                expires = converter(expires, expression, connection)
            if isinstance(expires, datetime) and expires < tz_now():
                msg = f"Key '{key}' not found"
                raise ValueError(msg)
            current = pickle.loads(  # noqa: S301  # nosec B301
                base64.b64decode(connection.ops.process_clob(raw_value).encode(), validate=True)
            )
            new_value = int(current) + delta
            encoded = base64.b64encode(pickle.dumps(new_value, self.pickle_protocol)).decode(
                "latin1"
            )
            cursor.execute(
                f"UPDATE {table} SET {quote('value')} = %s "  # noqa: S608  # nosec B608
                f"WHERE {quote('cache_key')} = %s",
                [encoded, cache_key],
            )
        return new_value

    def decr(self, key: Any, delta: int = 1, version: int | None = None) -> int:
        """کاهش اتمیک مقدار کلید."""
        return self.incr(key, -delta, version=version)
