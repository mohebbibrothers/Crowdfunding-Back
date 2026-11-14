#!/usr/bin/env python
"""سنجش هم‌گامی قرارداد با مولد ثابت ``drf-spectacular`` — مقایسهٔ معنایی.

چرا این اسکریپت وجود دارد
--------------------------
پیش از این CI با ``diff -u`` متنی فایل کامیت‌شده را با خروجی مولد مقایسه
می‌کرد. آن مقایسه ذاتاً شکننده بود: مولد نمونه (``yaml.safe_dump``) و
drf-spectacular متن‌های بلند فارسی را به عرض‌های متفاوتی می‌شکنند، پس دو
فایل با **محتوای کاملاً یکسان** بایت‌به‌بایت فرق داشتند. نتیجه: CI در
v1.5.0 قرمز شد در حالی که قرارداد سالم بود.

این اسکریپت همان قصد را برآورده می‌کند ولی بر اساس **ساختار پارس‌شده**:

1. نسخهٔ کامیت‌شده را می‌خواند و بلوک‌های ``examples`` را حذف می‌کند —
   چون آن‌ها خروجی ``compile_response_samples.py`` هستند، نه spectacular.
2. خروجی خام مولد را تازه تولید می‌کند.
3. دو درخت داده را با هم مقایسه می‌کند. اختلاف ⇒ خروج ۱ با diff خوانا.

اجرا در CI و محلی یکسان است:

    python scripts/verify_contract_sync.py
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, cast

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMITTED = REPO_ROOT / "docs" / "api" / "v1" / "openapi.yaml"
GENERATED = Path("/tmp/openapi.raw.yaml")  # noqa: S108 — مسیر موقت ثابت در CI و محلی

HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})


def _strip_examples(doc: dict[str, Any]) -> dict[str, Any]:
    """حذف نمونه‌های **تولیدی** (کلید ``realistic``) و نمونهٔ تزریقی بدنهٔ درخواست.

    نکتهٔ مهم: نمونه‌های **دست‌نویس** (کلید ``default`` در ``core/schema.py``)
    بخشی از قرارداد منبع‌اند و باید بمانند — فقط چیزی که این مخزن خودش تزریق
    می‌کند کنار گذاشته می‌شود. حذف همهٔ ``examples`` باعث می‌شد نمونه‌های
    دست‌نویس هم «اختلاف» شمرده شوند.
    """
    for item in doc.get("paths", {}).values():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            for response in operation.get("responses", {}).values():
                if not isinstance(response, dict):
                    continue
                for media in response.get("content", {}).values():
                    if not isinstance(media, dict):
                        continue
                    examples = media.get("examples")
                    if isinstance(examples, dict):
                        examples.pop("realistic", None)
                        if not examples:
                            media.pop("examples", None)
            request = operation.get("requestBody")
            if isinstance(request, dict):
                for media in request.get("content", {}).values():
                    if not isinstance(media, dict):
                        continue
                    examples = media.get("examples")
                    if isinstance(examples, dict):
                        examples.pop("realistic", None)
                        if not examples:
                            media.pop("examples", None)
                    media.pop("example", None)  # نمونهٔ بدنهٔ درخواست را همین مخزن تزریق می‌کند
    return doc


def _canonical(doc: dict[str, Any]) -> list[str]:
    """نمایش متنی پایدار یک سند برای مقایسه و diff خوانا."""
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1).splitlines()


def main() -> int:
    committed = cast(dict[str, Any], yaml.safe_load(COMMITTED.read_text(encoding="utf-8")))
    committed = _strip_examples(committed)

    subprocess.run(  # noqa: S603 — فرمان ثابت درون مخزن
        [
            sys.executable,
            str(REPO_ROOT / "src" / "manage.py"),
            "spectacular",
            "--api-version",
            "v1",
            "--file",
            str(GENERATED),
            "--validate",
            "--fail-on-warn",
        ],
        check=True,
        cwd=REPO_ROOT,
    )
    generated = cast(dict[str, Any], yaml.safe_load(GENERATED.read_text(encoding="utf-8")))

    if committed == generated:
        print("✅ قرارداد کامیت‌شده با خروجی مولد یکی است (مقایسهٔ معنایی، نمونه‌ها مستثنی).")
        return 0

    left = _canonical(generated)
    right = _canonical(committed)
    diff = list(difflib.unified_diff(left, right, "generated", "committed", lineterm=""))
    print("\n".join(diff[:200]))
    print(
        f"\n❌ قرارداد از مولد جدا شده است — {len(diff)} خط اختلاف. "
        "`make handoff` را اجرا و کامیت کنید.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
