"""نقطهٔ ورود استاندارد WSGI (سازگار با CloudLinux Passenger روی سی‌پنل نایترو و Gunicorn)."""

from __future__ import annotations

import os
from pathlib import Path
import sys

SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
