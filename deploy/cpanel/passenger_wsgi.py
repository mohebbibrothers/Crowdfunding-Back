"""نقطهٔ ورود استاندارد CloudLinux Phusion Passenger برای هاست اشتراکی/اختصاصی سی‌پنل نایترو.

نحوهٔ پیکربندی در «Setup Python App» سی‌پنل:
- Application root: `/home/<cpanel_user>/Crowdfunding-Back`
- Application startup file: `deploy/cpanel/passenger_wsgi.py`
- Application Entry point: `application`
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# بارگذاری ایمن فایل .env در ریشه پروژه در صورت وجود
_env_file = REPO_ROOT / ".env"
if _env_file.is_file():
    import environ

    environ.Env.read_env(str(_env_file), overwrite=False)

# سازگاری دوگانه درایور MySQL/MariaDB روی هاست‌های سی‌پنل:
# اگر کتابخانهٔ C (`MySQLdb` / `mysqlclient`) روی سرور نصب نبود، به صورت خودکار از `PyMySQL` استفاده می‌شود.
try:
    import MySQLdb  # noqa: F401
except ImportError:  # pragma: no cover
    import pymysql

    pymysql.version_info = (2, 2, 7, "final", 0)
    pymysql.install_as_MySQLdb()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

from config.wsgi import application  # noqa: E402

__all__ = ["application"]
