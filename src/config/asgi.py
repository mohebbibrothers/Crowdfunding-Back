"""نقطهٔ ورود استاندارد ASGI."""

from __future__ import annotations

import os
from pathlib import Path
import sys

SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

from django.core.asgi import get_asgi_application  # noqa: E402

application = get_asgi_application()
