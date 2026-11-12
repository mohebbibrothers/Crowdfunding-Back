#!/usr/bin/env python
"""نقطهٔ ورود خط فرمان جنگو برای سکوی کرادفاندینگ خیریه."""

from __future__ import annotations

import os
from pathlib import Path
import sys


def main() -> None:
    """اجرای فرمان‌های مدیریتی جنگو با مسیر دهی بستهٔ src."""
    src_dir = Path(__file__).resolve().parent
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
