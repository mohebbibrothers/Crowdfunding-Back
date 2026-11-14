#!/usr/bin/env python3
"""مولد نمونه‌های پاسخ قرارداد (Response Example Compiler).

═══════════════════════════════════════════════════════════════════════════════
مسئله‌ای که حل می‌کند

قرارداد ۱۰۴ عملیات و ۱۴۰ اسکیما دارد و همه تایپ‌شده‌اند — ولی تا امروز تك‌تك
آن‌ها **بدون یک نمونهٔ پاسخ واقعی** بودند. تیم فرانت باید از روی `$ref` و
`required` حدس می‌زد که JSON واقعی چه شکلی است: آیا تاریخ شمسی است یا ISO؟
مبلغ به ریال است یا تومان؟ فیلد خالی `null` می‌شود یا `""` یا حذف می‌شود؟

حدس زدن در این سه مورد، منبع اصلی باگ‌های یکپارچگی فرانت است.

راه‌حل

برای هر عملیات موفق، یک نمونهٔ **قطعی و قابل‌تکرار** از روی اسکیمای خودش
می‌سازیم، آن را با `jsonschema` اعتبارسنجی می‌کنیم، و در سه جا می‌نویسیم:

  ۱. `openapi.yaml` — به‌عنوان `examples` روی پاسخ موفق (Swagger UI زنده)
  ۲. `postman_collection.json` — به‌عنوان saved response (اجرا نمی‌خواهد)
  ۳. `docs/frontend/SAMPLES.md` — جدول خوانا برای انسان

اصل طراحی: **هیچ نمونهٔ دست‌نویس**. اگر اسکیما عوض شود، نمونه خودکار عوض
می‌شود. نمونهٔ دست‌نویس با گذشت زمان دروغ می‌گوید و کسی متوجه نمی‌شود.

نکتهٔ ظریف: مقادیر بر اساس **نام فیلد** انتخاب می‌شوند، نه تصادفی. `amount_rial`
باید عددی چندهزار باشد نه ۴۲؛ `due_date` باید تاریخ باشد نه رشتهٔ «string».
نمونه‌ای که شکل واقعی را نشان ندهد، بدتر از نبودنش است.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, cast

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs" / "api" / "v1" / "openapi.yaml"
OUT = ROOT / "docs" / "frontend"
HTTP_METHODS = ("get", "post", "patch", "put", "delete")

# ══════════════════════════════════════════════════════════════════════════════
# ۱) تولید مقدار از روی نام فیلد
#
# این جدول قلب کیفیت است. نمونه‌ای که اینجا خوب انتخاب نشود، در تمام ۱۰۴
# عملیات بد ظاهر می‌شود. اولویت: خاص‌ترین الگو اول.
# ══════════════════════════════════════════════════════════════════════════════

# (regex روی نام فیلد، (مقدار، توضیح کوتاه))
FIELD_RULES: tuple[tuple[str, Any], ...] = (
    # ── شناسه‌ها ──────────────────────────────────────────────────────────────
    (r"^id$|_id$", "0b5f3f1e-8c9a-4d2b-9e7f-2a1c4d5e6f70"),
    (r"^uuid$", "0b5f3f1e-8c9a-4d2b-9e7f-2a1c4d5e6f70"),
    # ── پول: همیشه عدد چندهزارتایی، هرگز ۰ یا ۱ ──────────────────────────────
    # قاعدهٔ ``_rial$`` گرید است و ``installments_paid_rial`` را هم می‌گیرد؛
    # ولی اشتباه بزرگ‌تر این بود که ``installments_paid`` را هم پول می‌دید.
    # ترتیب: مفاهیم شمارشی پیش از پول، چون «تعداد قسط» پول نیست.
    (r"installments_paid$|installments_skipped$|installments_count$", 7),
    (r"amount_rial$|_rial$", 1_500_000),
    (r"amount_toman$|_toman$", 150_000),
    # ── تاریخ‌ها ──────────────────────────────────────────────────────────────
    (r"date$|_date$", "2026-11-12"),
    (r"datetime$|_at$|timestamp$", "2026-11-12T09:41:00+03:30"),
    (r"jalali$", "۱۷ آبان ۱۴۰۵"),
    # ── موبایل و ایمیل ───────────────────────────────────────────────────────
    (r"phone|mobile", "09121234567"),
    (r"email", "donor@example.com"),
    # ── متن‌های معنادار ──────────────────────────────────────────────────────
    (r"title$", "تأمین جهیزیهٔ ۱۲ نوعروس"),
    # ``gateway_name`` به ``_name$`` می‌خورد و «سارا محمدی» می‌گرفت — نمونه‌ای
    # که معنا را وارونه نشان می‌دهد. نام درگاه پیش از هر قاعدهٔ عمومی می‌آید.
    (r"gateway_name", "zarinpal"),
    (r"_display$", "نمایش خوانا"),
    (r"icon_name|image_name|file_name|username", "icon-heart"),
    (r"^name$|^full_name$|_name$", "سارا محمدی"),
    (r"slug$", "tamin-jahizieh"),
    (r"code$|short_code$", "cf-8k2m"),
    (r"token|authority", "A0000000000000000000000000000021799"),
    (
        r"sha256|hash|fingerprint",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    (r"url|link|uri", "https://example.com/x"),
    (r"iban", "IR0170000000009988776655"),
    (r"note|comment|description|reason|memo|bio", "توضیح کوتاه"),
    (r"city|province", "تهران"),
    (r"currency$", "IRR"),
    # ── شمارنده‌ها: عدد مثبت کوچک، نه صفر ─────────────────────────────────────
    (r"count$|_count$|^total$|total_|_total", 12),
    (r"page_size|page|limit", 20),
    # ── درصدها: عدد صحیح ۰ تا ۱۰۰ (فیلدهای ``*_percent`` در این پروژه
    #    ``PositiveSmallIntegerField`` هستند، نه نسبت اعشاری). این تفکیک مهم
    #    است: نمونه‌ای با ۰.۸۴ روی فیلد صحیح، اعتبارسنجی را می‌شکند و فرانت
    #    نمی‌داند کدام را باور کند.
    (r"percent$|_percent$|pct$", 84),
    # ── نسبت‌ها: بین ۰ و ۱ ───────────────────────────────────────────────────
    # ``ratio`` در این پروژه صحیح است (``match_ratio`` = «هر سهم = N سهم»).
    # نسبت اعشاری فقط برای ``rate`` که درصد موفقیت است.
    (r"ratio$", 2),
    (r"^rate$|_rate$", 0.8421),
    # ── پرچم‌ها ──────────────────────────────────────────────────────────────
    (r"^is_|^has_|^can_|^should_|enabled$", True),
    # ── نسخه ─────────────────────────────────────────────────────────────────
    (r"version$", "1.4.0"),
)

# فیلدهای «پولی» که نباید صفر باشند ولی نامشان الگوی بالا را نگرفت
MONEY_HINTS = ("rial", "toman", "amount", "price", "cost", "balance", "paid", "fee")

# فیلدهایی که مقدارشان باید از enum باشد — با ارجاع به `$ref` شناسایی می‌شوند
MAX_DEPTH = 12
DEFAULT_COUNT = 2  # تعداد آیتم در آرایه‌ها؛ ۲ بهتر از ۱ است چون «فهرست» را نشان می‌دهد


def _by_name(name: str, typ: str) -> tuple[Any, bool]:
    """انتخاب مقدار از روی نام فیلد. خروجی دوم: آیا قاعده اعمال شد."""
    lowered = name.lower()
    for pattern, value in FIELD_RULES:
        if re.search(pattern, lowered):
            # اگر اسکیما رشته است ولی قاعده عدد داد، به رشته تبدیل کن و برعکس
            if typ == "string" and not isinstance(value, str):
                return str(value), True
            if typ in {"integer", "number"} and isinstance(value, str):
                return DEFAULT_COUNT, True
            if typ == "boolean" and not isinstance(value, bool):
                continue
            return value, True

    # «تعداد» پیش از «پول» بررسی می‌شود: ``installments_paid`` شامل «paid»
    # است ولی تعداد است نه مبلغ. نمونه‌ای با ۱٬۵۰۰٬۰۰۰ قسط پرداخت‌شده،
    # فرانت را گمراه می‌کند و در دموی محصول مسخره به‌نظر می‌رسد.
    if typ in {"integer", "number"} and re.search(
        r"count$|_count$|^num_|_num$|installments_paid$|installments_skipped$", lowered
    ):
        return DEFAULT_COUNT, True
    if any(hint in lowered for hint in MONEY_HINTS) and typ in {"integer", "number"}:
        return 1_500_000, True

    if typ == "integer":
        return DEFAULT_COUNT, False
    if typ == "number":
        return 1.0, False
    if typ == "boolean":
        return True, False
    return "string", False


def _resolve(schema: dict[str, Any], doc: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """باز‌کردن `$ref` (با محافظ در برابر حلقهٔ بی‌پایان)."""
    if depth > MAX_DEPTH:
        return {}
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        # /// و نه split("/")[2:]: مسیر ``#/components/schemas/X`` سه بخش دارد
        # و پرش از ``components`` باعث می‌شد ارجاع بی‌صدا به ``{}`` تبدیل شود —
        # یعنی هر آرایهٔ ``$ref`` به ``[null, null]``. نمونهٔ خراب بدتر از
        # نبودن نمونه است: فرانت فکر می‌کند پاسخ واقعاً null است.
        node: Any = doc
        for part in ref.removeprefix("#/").split("/"):
            if not isinstance(node, dict) or part not in node:
                # ارجاع شکسته باید صریح باشد، نه بی‌صدا.
                raise KeyError(f"ارجاع شکسته در قرارداد: {ref} (بخش «{part}» یافت نشد)")
            node = node[part]
        if isinstance(node, dict):
            return node
    return schema


def _variant(value: Any, index: int) -> Any:
    """تنوع معنادار برای آیتم دوم فهرست — تا نمونه «فهرست یک‌عضوی» به‌نظر نرسد."""
    if isinstance(value, str):
        if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value):
            return f"{value[:-2]}{index:02d}"
        return f"{value}-{index + 1}"
    if isinstance(value, int):
        return value + index
    return value


def _pick_enum(value: Any) -> Any:
    """اولین گزینهٔ غیرخالی enum — نه اولین گزینه (که اغلب خالی یا پیش‌فرض است)."""
    if not isinstance(value, list):
        return value
    candidates = [v for v in value if v not in (None, "", [], {})]
    return candidates[0] if candidates else (value[0] if value else "string")


def sample_value(
    schema: dict[str, Any],
    doc: dict[str, Any],
    name: str = "",
    depth: int = 0,
) -> Any:
    """ساخت یک مقدار نمونهٔ معتبر از روی اسکیما.

    ترتیب اولویت عمدی است: `enum` و `const` مقدم بر `type` هستند چون یک نمونهٔ
    بیرون از enum، بنر قرمز Swagger و شکست اعتبارسنجی می‌دهد.
    """
    schema = _resolve(schema, doc, depth)
    if depth > MAX_DEPTH or not schema:
        return None

    # ترکیب‌ها (allOf/oneOf/anyOf) — اولین شاخهٔ غیرnull
    for key in ("oneOf", "anyOf"):
        if key in schema and isinstance(schema[key], list):
            options = [s for s in schema[key] if _resolve(s, doc, depth + 1).get("type") != "null"]
            if options:
                return sample_value(options[0], doc, name, depth + 1)
    if "allOf" in schema and isinstance(schema["allOf"], list):
        # حالت رایج در drf-spectacular: ``allOf: [{$ref: X}]`` برای چسباندن
        # توضیح به یک enum. اگر اینجا را به «ادغام شیء» تعبیر کنیم، enum از
        # دست می‌رود و نمونه ``{}`` می‌شود — همان باگی که match_status گرفت.
        # قاعده: اگر تک‌عضوی و همان یک عضو، خودش را حل کن، نه اینکه شیء بسازی.
        parts = schema["allOf"]
        if len(parts) == 1:
            return sample_value(parts[0], doc, name, depth + 1)

        merged: dict[str, Any] = {"type": "object", "properties": {}}
        for sub in parts:
            resolved = _resolve(sub, doc, depth + 1)
            if resolved.get("type") not in (None, "object") or "enum" in resolved:
                return sample_value(sub, doc, name, depth + 1)
            merged["properties"].update(resolved.get("properties", {}))
            merged.setdefault("required", [])
            merged["required"] += resolved.get("required", [])
        merged.update({k: v for k, v in schema.items() if k != "allOf"})
        return sample_value(merged, doc, name, depth + 1)

    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return _pick_enum(schema["enum"])

    # فیلد nullable → null واقعی. برخلاف تصور رایج، «نمونهٔ پر» همیشه بهتر
    # نیست: اگر فرانت نبیند که ``pause_until`` می‌تواند null باشد، اولین
    # تعهد متوقف، رابط را می‌شکند. ولی null فقط برای فیلد اختیاری، وگرنه
    # نمونه با ``required`` تضاد پیدا می‌کند.
    # دو نمایش nullable در OpenAPI: فرم قدیمی ``nullable: true`` و فرم
    # 3.1 ``type: [T, "null"]``. drf-spectacular دومی را تولید می‌کند، پس
    # فقط چک اول یعنی هیچ فیلد nullable در نمونه null نمی‌شود و فرانت هرگز
    # نمی‌فهمد ``pause_until`` می‌تواند وجود نداشته باشد.
    raw_type = schema.get("type")
    is_nullable_form2 = isinstance(raw_type, list) and "null" in raw_type
    if (
        schema.get("nullable") is True or (is_nullable_form2 and "default" not in schema)
    ) and "default" not in schema:
        return None

    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]

    typ = schema.get("type")
    if isinstance(typ, list):
        typ = next((t for t in typ if t != "null"), "string")

    if typ == "object" or "properties" in schema:
        return _build_object(_resolve(schema, doc, depth), doc, depth + 1)

    if typ == "array":
        items = schema.get("items", {})
        resolved_items = _resolve(items, doc, depth + 1)
        count = DEFAULT_COUNT
        if resolved_items.get("type") == "string" and "enum" in resolved_items:
            # برای enum کوتاه، همهٔ گزینه‌ها؛ نه تکرار یک مقدار
            count = min(len(resolved_items["enum"]), DEFAULT_COUNT)
        built = [sample_value(items, doc, name, depth + 1) for _ in range(count)]
        # دو آیتم کاملاً یکسان، «فهرست» را نشان نمی‌دهد و فرانت نمی‌فهمد کدام
        # فیلد کلید است. آیتم دوم را در فیلدهای متنی/شناسه‌ای متفاوت می‌کنیم.
        for index in range(1, len(built)):
            if isinstance(built[index], dict) and isinstance(built[0], dict):
                for key in ("id", "title", "name", "slug", "code", "sequence"):
                    if key in built[index]:
                        built[index][key] = _variant(built[index][key], index)
                        break
            elif isinstance(built[index], (int, float)) and not isinstance(built[index], bool):
                # ``bad_anchors: [2, 2]`` یعنی «دو锚 خراب» ولی دو بار همان ۲ —
                # فرانت نمی‌فهمد شماره‌اند یا شمارش. عدد را یکتا می‌کنیم.
                built[index] = built[index] + index * 7
        return built

    # ترتیب: enum و const پیش‌تر بررسی شدند. اینجا نوبت قواعد «بر اساس نام» است.
    # یک فیلد با ``type: string`` و ``enum: [sandbox, zarinpal]`` هرگز نباید
    # «سارا محمدی» بگیرد — نمونهٔ بیرون از enum، بنر قرمز Swagger می‌دهد.
    return _by_name(name, str(typ or "string"))[0]


def _build_object(schema: dict[str, Any], doc: dict[str, Any], depth: int) -> dict[str, Any]:
    """ساخت شیء از `properties` (فقط فیلدهای required + چند فیلد اختیاری معنادار)."""
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    if not isinstance(props, dict):
        return {}

    out: dict[str, Any] = {}
    for key, sub in props.items():
        # فیلدهای اختیاری را هم می‌آوریم مگر آنکه خیلی زیاد باشند — نمونه‌ای که
        # فقط کلیدهای الزامی را دارد، ظاهر واقعی پاسخ را نشان نمی‌دهد.
        value = sample_value(cast(dict[str, Any], sub), doc, key, depth)
        if value is None and key not in required:
            continue
        out[key] = value

    for extra in required - set(out):
        out[extra] = sample_value(props.get(extra, {}), doc, extra, depth)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# ۲) ساخت اسکیمای OpenAPI 3.1 ↔ jsonschema (برای اعتبارسنجی)
# ══════════════════════════════════════════════════════════════════════════════


def to_validator_schema(
    schema: dict[str, Any], doc: dict[str, Any], depth: int = 0
) -> dict[str, Any]:
    """تبدیل اسکیمای OpenAPI 3.1 به اسکیمای قابل‌اعتبارسنجی با jsonschema.

    OpenAPI 3.1 تقریباً JSON Schema است، ولی سه تفاوت دارد که اعتبارسنجی را
    می‌شکند: `nullable` (جای `type: [x, null]`)، `$ref`های داخلی، و
    `exclusiveMinimum` عددی. هر سه حل می‌شوند.
    """
    if depth > MAX_DEPTH:
        return {}
    schema = _resolve(schema, doc, depth)
    if not isinstance(schema, dict):
        return {}

    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in {
            "nullable",
            "example",
            "examples",
            "deprecated",
            "readOnly",
            "writeOnly",
            "xml",
            "discriminator",
            "externalDocs",
        }:
            continue
        if key == "properties" and isinstance(value, dict):
            out["properties"] = {
                k: to_validator_schema(cast(dict[str, Any], v), doc, depth + 1)
                for k, v in value.items()
            }
        elif key == "items":
            out["items"] = to_validator_schema(cast(dict[str, Any], value), doc, depth + 1)
        elif key in {"oneOf", "anyOf", "allOf"} and isinstance(value, list):
            out[key] = [to_validator_schema(cast(dict[str, Any], v), doc, depth + 1) for v in value]
        elif key == "additionalProperties" and isinstance(value, dict):
            out[key] = to_validator_schema(cast(dict[str, Any], value), doc, depth + 1)
        else:
            out[key] = value

    if schema.get("nullable") and "type" in out:
        out["type"] = [out["type"], "null"] if isinstance(out["type"], str) else out["type"]
    out.pop("nullable", None)
    return out


def validate_sample(sample: Any, schema: dict[str, Any], doc: dict[str, Any]) -> str | None:
    """اعتبارسنجی نمونه در برابر اسکیما. خروجی: پیام خطا یا None."""
    try:
        validator_schema = to_validator_schema(schema, doc)
        jsonschema.validate(instance=sample, schema=validator_schema)
    except jsonschema.ValidationError as exc:
        path = "/".join(str(p) for p in exc.absolute_path) or "<root>"
        return f"{path}: {exc.message[:160]}"
    except jsonschema.SchemaError as exc:  # pragma: no cover - اسکیمای معیوب
        return f"schema-error: {exc.message[:160]}"
    return None


# ══════════════════════════════════════════════════════════════════════════════
# ۳) عملیات
# ══════════════════════════════════════════════════════════════════════════════


def success_responses(operation: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """**همهٔ** پاسخ‌های موفق با اسکیما — نه فقط اولی.

    چرا جمعی و نه یکی؟ چون یک عملیات می‌تواند دو حالت موفق داشته باشد:
    ``POST /admin/settlements`` برای بار اول ۲۰۱ و برای همان فایل دوباره
    ۲۰۰ برمی‌گرداند (idempotent ingest). اگر فقط اولی نمونه بگیرد، تیم
    فرانت برای حالت دوم هیچ نمونه‌ای ندارد و نمی‌داند پاسخ ۲۰۰ چه شکلی است.
    """
    found: list[tuple[str, dict[str, Any]]] = []
    for status, resp in operation.get("responses", {}).items():
        if not str(status).startswith("2") or not isinstance(resp, dict):
            continue
        for media in resp.get("content", {}).values():
            if isinstance(media, dict) and media.get("schema"):
                found.append((str(status), cast(dict[str, Any], media["schema"])))
                break
    return found


def request_example(operation: dict[str, Any], doc: dict[str, Any]) -> Any:
    """نمونهٔ بدنهٔ درخواست، اگر وجود دارد و از قبل نمونه ندارد."""
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        return None
    for media in body.get("content", {}).values():
        if not isinstance(media, dict) or not media.get("schema"):
            continue
        if media.get("example") or media.get("examples"):
            return media.get("example") or next(iter(media["examples"].values()), {}).get("value")
        return sample_value(cast(dict[str, Any], media["schema"]), doc, "request")
    return None


def build(doc: dict[str, Any]) -> dict[str, Any]:
    """تولید نمونه‌ها، اعتبارسنجی و تزریق در قرارداد. خروجی: گزارش."""
    report: dict[str, Any] = {
        "operations": 0,
        "responses_sampled": 0,
        "requests_sampled": 0,
        "validation_failures": [],
        "skipped_no_schema": [],
    }

    for path, item in doc.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            report["operations"] += 1

            found = success_responses(cast(dict[str, Any], operation))
            if not found:
                report["skipped_no_schema"].append(f"{method.upper()} {path}")
                continue

            for status, schema in found:
                sample = sample_value(schema, doc, "response")
                problem = validate_sample(sample, schema, doc)
                if problem is not None:
                    report["validation_failures"].append(
                        {
                            "operation": f"{method.upper()} {path}",
                            "status": status,
                            "reason": problem,
                        }
                    )
                    continue

                media = operation["responses"][status]["content"].setdefault("application/json", {})
                media.setdefault(
                    "examples",
                    {
                        "realistic": {
                            "summary": "نمونهٔ واقعیِ تولیدشده از همین اسکیما",
                            "description": (
                                "این مقدار از روی اسکیمای همین پاسخ ساخته و با jsonschema "
                                "اعتبارسنجی شده است؛ مقادیر بر اساس معنای نام فیلد انتخاب شده‌اند."
                            ),
                            "value": sample,
                        }
                    },
                )
                report["responses_sampled"] += 1

            req = request_example(cast(dict[str, Any], operation), doc)
            if req is not None:
                for media in operation["requestBody"]["content"].values():
                    if (
                        isinstance(media, dict)
                        and not media.get("example")
                        and not media.get("examples")
                    ):
                        media["example"] = req
                        report["requests_sampled"] += 1
                        break

    return report


def write_samples_markdown(doc: dict[str, Any]) -> int:
    """جدول خوانای نمونه‌ها برای انسان — نه برای ماشین."""
    rows: list[str] = [
        "# نمونهٔ پاسخ — همهٔ عملیات",
        "",
        "> تولیدشده با `scripts/compile_response_samples.py`. **دستکاری نکنید**؛",
        "> اسکریپت در CI اجرا می‌شود و هر اختلافی گیت را قرمز می‌کند.",
        "",
        "هر نمونه از روی اسکیمای همان پاسخ ساخته و با `jsonschema` اعتبارسنجی شده است:",
        "اگر اسکیما عوض شود، نمونه هم عوض می‌شود — نمونهٔ دست‌نویس با گذشت زمان دروغ می‌گوید.",
        "",
        "| عملیات | status | نمونه |",
        "| --- | --- | --- |",
    ]
    count = 0
    for path, item in doc.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            for status, _schema in success_responses(cast(dict[str, Any], operation)):
                media = (
                    operation["responses"][status].get("content", {}).get("application/json", {})
                )
                value = (media.get("examples", {}).get("realistic", {}) or {}).get("value")
                if value is None:
                    continue
                payload = json.dumps(value, ensure_ascii=False)
                if len(payload) > 220:
                    payload = payload[:217] + "…"
                rows.append(f"| `{method.upper()} {path}` | {status} | `{payload}` |")
                count += 1
    (OUT / "SAMPLES.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return count


def main() -> None:
    """اجرای کامل: خواندن، تولید، اعتبارسنجی، نوشتن."""
    raw = SCHEMA_PATH.read_text(encoding="utf-8")
    doc = cast(dict[str, Any], yaml.safe_load(raw))
    report = build(doc)

    SCHEMA_PATH.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )

    digest = hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()
    print(
        f"نمونه‌سازی: {report['responses_sampled']}/{report['operations']} پاسخ، "
        f"{report['requests_sampled']} بدنهٔ درخواست"
    )
    print(f"اثر انگشت قرارداد پس از نمونه‌سازی: {digest[:16]}…")

    if report["validation_failures"]:
        print(f"\n❌ {len(report['validation_failures'])} نمونه نامعتبر:")
        for row in report["validation_failures"][:20]:
            print(f"   {row['operation']} [{row['status']}] → {row['reason']}")
        raise SystemExit(1)

    if report["skipped_no_schema"]:
        print(f"⚠️  {len(report['skipped_no_schema'])} عملیات بدون اسکیمای پاسخ:")
        for row in report["skipped_no_schema"][:10]:
            print("   ", row)

    written = write_samples_markdown(doc)
    print(f"SAMPLES.md: {written} نمونه")


if __name__ == "__main__":
    main()
