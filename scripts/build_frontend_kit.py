#!/usr/bin/env python3
"""کامپایلر بستهٔ تحویل فرانتاند (Contract-First Frontend Kit Builder).

منبع حقیقت واحد: ``docs/api/v1/openapi.yaml`` و ``PROBLEM_CODES`` در ``apps/core/schema.py``.
خروجیها کاملاً تعیینی (deterministic) هستند تا CI بتواند با diff از همگامبودن آنها مطمئن شود:

  • docs/frontend/ENDPOINTS.md              ماتریس کامل ۸۳ عملیات
  • docs/frontend/ERRORS.md                کاتالوگ RFC 9457 + راهکار UX
  • docs/frontend/api-types.d.ts           تایپهای TypeScript تولیدشده از components
  • docs/frontend/postman_collection.json  کالکشن قابل import در Postman/Bruno
  • docs/frontend/contract-fingerprint.json  اثر انگشت قرارداد برای گیت CI
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
from typing import Any, cast

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs" / "api" / "v1" / "openapi.yaml"
OUT = ROOT / "docs" / "frontend"
HTTP_METHODS = ("get", "post", "patch", "put", "delete")
TS_RESERVED = {"default", "class", "function", "new", "delete", "enum", "interface", "type"}


def load_schema() -> dict[str, Any]:
    """خواندن و اعتبارسنجی حداقلی قرارداد OpenAPI 3.1."""
    doc = cast(dict[str, Any], yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8")))
    assert str(doc.get("openapi", "")).startswith("3.1."), "OpenAPI 3.1 required"
    assert doc.get("servers"), "servers must be declared for frontend clients"
    assert doc.get("components", {}).get("schemas", {}).get("Problem"), "Problem schema missing"
    return doc


def load_problem_codes() -> list[tuple[str, int, str, str, str]]:
    """استخراج کاتالوگ کانونی خطاها با AST (بدون نیاز به راهاندازی جنگو)."""
    source = (ROOT / "src" / "apps" / "core" / "schema.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "PROBLEM_CODES"
            and node.value is not None
        ):
            return [tuple(row) for row in ast.literal_eval(node.value)]  # type: ignore[misc]
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PROBLEM_CODES":
                    return [tuple(row) for row in ast.literal_eval(node.value)]  # type: ignore[misc]
    raise AssertionError("PROBLEM_CODES not found in apps/core/schema.py")


def operations(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """تبدیل ساختار paths به فهرست تخت عملیاتها."""
    rows: list[dict[str, Any]] = []
    for path, item in doc["paths"].items():
        for method, spec in item.items():
            if method not in HTTP_METHODS:
                continue
            rows.append(
                {
                    "path": path,
                    "method": method.upper(),
                    "operationId": spec["operationId"],
                    "summary": spec.get("summary", ""),
                    "tags": spec.get("tags", ["Untagged"]),
                    "security": spec.get("security", []),
                    "parameters": spec.get("parameters", []),
                    "requestBody": spec.get("requestBody"),
                    "responses": spec.get("responses", {}),
                    "policy": spec.get("x-frontend-policy", {}),
                }
            )
    return sorted(rows, key=lambda r: (r["tags"][0], r["path"], r["method"]))


def ref_name(schema: Any) -> str | None:
    """استخراج نام کامپوننت از یک $ref."""
    if isinstance(schema, dict) and "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[-1]
    return None


# ─── TypeScript ────────────────────────────────────────────────────────────────


def ts_type(schema: Any, *, depth: int = 0) -> str:
    """نگاشت اسکیمای OpenAPI 3.1 به نوع TypeScript."""
    if not isinstance(schema, dict):
        return "unknown"
    if "$ref" in schema:
        return ref_name(schema) or "unknown"
    if "enum" in schema:
        return " | ".join(json.dumps(v, ensure_ascii=False) for v in schema["enum"])
    if "oneOf" in schema or "anyOf" in schema:
        parts = schema.get("oneOf") or schema.get("anyOf") or []
        return " | ".join(ts_type(s, depth=depth + 1) for s in parts)
    if "allOf" in schema:
        return " & ".join(ts_type(s, depth=depth + 1) for s in schema["allOf"])
    raw_type = schema.get("type")
    types = raw_type if isinstance(raw_type, list) else [raw_type]
    non_null = [t for t in types if t != "null"]
    nullable = "null" in types
    base = "unknown"
    if non_null:
        t = non_null[0]
        if t == "string":
            fmt = schema.get("format")
            # date-time → رشتهٔ ISO-8601 (رانتایم ``+03:30`` می‌فرستد؛ نه epoch)
            # binary → Blob (پاسخ xlsx/فایل؛ fetch().blob())
            base = "Blob" if fmt == "binary" else "string"
        elif t in {"integer", "number"}:
            base = "number"
        elif t == "boolean":
            base = "boolean"
        elif t == "array":
            base = f"Array<{ts_type(schema.get('items', {}), depth=depth + 1)}>"
        elif t == "object":
            props = schema.get("properties")
            if props:
                required = set(schema.get("required", []))
                lines = []
                for key, sub in props.items():
                    safe = key if re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", key) else json.dumps(key)
                    if safe in TS_RESERVED:
                        safe = json.dumps(key)
                    optional = "" if key in required else "?"
                    lines.append(f"{safe}{optional}: {ts_type(sub, depth=depth + 1)};")
                base = "{ " + " ".join(lines) + " }"
            elif schema.get("additionalProperties"):
                base = f"Record<string, {ts_type(schema['additionalProperties'], depth=depth + 1)}>"
            else:
                base = "Record<string, unknown>"
    if nullable:
        base = f"({base} | null)"
    return base


def ts_identifier(name: str) -> str:
    """تبدیل نام کامپوننت به شناسهٔ معتبر TypeScript."""
    cleaned = re.sub(r"[^A-Za-z0-9_$]", "_", name)
    if cleaned and cleaned[0].isdigit():
        cleaned = f"S{cleaned}"
    return cleaned[0].upper() + cleaned[1:] if cleaned else "Anonymous"


def build_types(doc: dict[str, Any], ops: list[dict[str, Any]]) -> str:
    """تولید فایل تعاریف تایپشده با تایپهای پاسخ/درخواست هر operationId."""
    schemas: dict[str, Any] = doc["components"]["schemas"]
    lines = [
        "// ═══════════════════════════════════════════════════════════════════════════",
        "// Crowdfunding-Back — تعاریف TypeScript تولیدشدهٔ خودکار از OpenAPI 3.1.0",
        "// ⚠️  این فایل را دستکاری نکنید؛ با `make handoff` بازتولید میشود.",
        "// منبع حقیقت: docs/api/v1/openapi.yaml",
        "// ═══════════════════════════════════════════════════════════════════════════",
        "",
        "export type ProblemCode =",
    ]
    codes = doc["components"]["schemas"]["Problem"]["properties"]["code"]["enum"]
    for code in codes:
        lines.append(f"  | {json.dumps(code, ensure_ascii=False)}")
    lines[-1] += ";"
    lines.extend(["", "export interface ApiError {", "  type: string;", "  title: string;"])
    lines.append("  status: number;")
    lines.append("  detail: string;")
    lines.append("  code: ProblemCode;")
    lines.append("  instance: string;")
    lines.append("  trace_id: string;")
    lines.append("  errors?: Record<string, string[]>;")
    lines.append("  retry_after?: number;")
    lines.extend(["}", "", "export interface CursorMeta {"])
    lines.append("  next: string | null;")
    lines.append("  previous: string | null;")
    lines.append("  page_size: number;")
    lines.append("  total?: number;")
    lines.extend(["}", ""])

    for name, schema in sorted(schemas.items()):
        ident = ts_identifier(name)
        if ident == "Problem":
            continue
        body = ts_type(schema)
        lines.append(f"/** {schema.get('description') or name} */")
        if body.startswith("{ "):
            lines.append(f"export interface {ident} {body}")
        else:
            lines.append(f"export type {ident} = {body};")
        lines.append("")

    lines.extend(
        [
            "export type ApiOperationId =",
        ]
    )
    for row in ops:
        lines.append(f"  | {json.dumps(row['operationId'])}")
    lines[-1] += ";"
    lines.extend(["", "export interface ApiOperationMap {"])
    for row in ops:
        success = next(
            (r for status, r in sorted(row["responses"].items()) if str(status).startswith("2")),
            None,
        )
        response_type = "void"
        if success:
            content = success.get("content", {})
            for media in content.values():
                if not isinstance(media, dict) or "schema" not in media:
                    continue
                candidate = ref_name(media["schema"])
                response_type = ts_identifier(candidate) if candidate else ts_type(media["schema"])
                break
        request_type = "never"
        rb = row["requestBody"]
        if isinstance(rb, dict):
            for media in rb.get("content", {}).values():
                if not isinstance(media, dict) or "schema" not in media:
                    continue
                candidate = ref_name(media["schema"])
                request_type = ts_identifier(candidate) if candidate else ts_type(media["schema"])
                break
        lines.append(
            f"  {json.dumps(row['operationId'])}: {{ request: {request_type}; "
            f"response: {response_type}; auth: "
            f"{json.dumps(row['policy'].get('auth', 'required'))} }};"
        )
    lines.extend(
        ["}", "", "export type ApiOperation<K extends ApiOperationId> = ApiOperationMap[K];", ""]
    )
    return "\n".join(lines)


# ─── Postman / Bruno ───────────────────────────────────────────────────────────


def postman_url(path: str) -> dict[str, Any]:
    """ساخت ساختار URL قابل import با متغیر baseUrl."""
    path_vars = re.findall(r"\{([^}]+)\}", path)
    converted = re.sub(r"\{([^}]+)\}", r":\1", path)
    return {
        "raw": "{{baseUrl}}" + converted,
        "host": ["{{baseUrl}}"],
        "path": [p for p in converted.strip("/").split("/") if p],
        "variable": [{"key": v, "value": f"<{v}>"} for v in path_vars],
    }


def build_operations_ts(ops: list[dict[str, Any]]) -> str:
    """نگاشت ایستای operationId → متد/مسیر، برای فراخوانی تایپشدهٔ کلاینت."""
    lines = [
        "// ═══════════════════════════════════════════════════════════════════════════",
        "// نگاشت عملیاتها — تولیدشدهٔ خودکار از docs/api/v1/openapi.yaml",
        "// ⚠️  دستکاری نکنید؛ با `make handoff` بازتولید میشود.",
        "// ═══════════════════════════════════════════════════════════════════════════",
        "",
        "export type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';",
        "",
        "export interface OperationDescriptor {",
        "  readonly method: HttpMethod;",
        "  readonly path: string;",
        "  readonly operationId: string;",
        "}",
        "",
        "export const OPERATIONS = {",
    ]
    for row in ops:
        lines.append(
            f"  {json.dumps(row['operationId'])}: "
            f"{{ method: {json.dumps(row['method'])}, path: {json.dumps(row['path'])}, "
            f"operationId: {json.dumps(row['operationId'])} }},"
        )
    lines.extend(["} as const;", "", "export type OperationKey = keyof typeof OPERATIONS;", ""])
    return "\n".join(lines)


def build_postman(doc: dict[str, Any], ops: list[dict[str, Any]]) -> dict[str, Any]:
    """تولید کالکشن Postman v2.1 دستهبندیشده بر پایهٔ تگها."""
    folders: dict[str, list[dict[str, Any]]] = {}
    for row in ops:
        tag = row["tags"][0]
        headers = [
            {"key": "Accept", "value": "application/json"},
            {"key": "X-Request-ID", "value": "{{$guid}}", "disabled": True},
        ]
        auth_policy = row["policy"].get("auth", "required")
        if auth_policy != "none":
            headers.append(
                {
                    "key": "Authorization",
                    "value": "Bearer {{accessToken}}",
                    "disabled": auth_policy == "optional",
                }
            )
        if row["method"] in {"POST", "PATCH", "PUT", "DELETE"}:
            headers.append({"key": "X-CSRFToken", "value": "{{csrfToken}}", "disabled": True})
            headers.append({"key": "Idempotency-Key", "value": "{{$guid}}", "disabled": True})
        for param in row["parameters"]:
            if param.get("in") == "header":
                headers.append(
                    {
                        "key": param["name"],
                        "value": f"<{param['name']}>",
                        "disabled": True,
                        "description": param.get("description", ""),
                    }
                )

        body: dict[str, Any] = {}
        rb = row["requestBody"]
        if isinstance(rb, dict):
            example = (
                rb.get("content", {})
                .get("application/json", {})
                .get("examples", {})
                .get("default", {})
                .get("value")
            )
            raw_value = json.dumps(
                example if example is not None else {}, ensure_ascii=False, indent=2
            )
            body = {
                "mode": "raw",
                "raw": raw_value,
                "options": {"raw": {"language": "json"}},
            }

        query = [
            {
                "key": p["name"],
                "value": f"<{p['name']}>",
                "disabled": True,
                "description": p.get("description", ""),
            }
            for p in row["parameters"]
            if p.get("in") == "query"
        ]
        item: dict[str, Any] = {
            "name": row["summary"] or row["operationId"],
            "request": {
                "method": row["method"],
                "header": headers,
                "url": {**postman_url(row["path"]), "query": query},
                "description": (
                    f"`{row['operationId']}` — {row['summary']}\n"
                    f"خطاها: application/problem+json | سیاست: {row['policy'].get('auth')}"
                ),
            },
            "response": [],
        }
        if body:
            item["request"]["body"] = body
        folders.setdefault(tag, []).append(item)

    return {
        "info": {
            "name": "Crowdfunding-Back API v1 — بستهٔ تحویل فرانتاند",
            "description": (
                "تولیدشدهٔ خودکار از docs/api/v1/openapi.yaml | "
                "خطاها RFC 9457 | مبالغ ریال صحیح + معادل تومانی | تاریخها شمسی"
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [{"name": tag, "item": items} for tag, items in sorted(folders.items())],
        "variable": [
            {"key": "baseUrl", "value": doc["servers"][0]["url"]},
            {"key": "accessToken", "value": "<JWT access token>"},
            {"key": "csrfToken", "value": "<GET /api/v1/auth/csrf>"},
        ],
    }


# ─── Markdown ─────────────────────────────────────────────────────────────────


def build_endpoints_md(doc: dict[str, Any], ops: list[dict[str, Any]]) -> str:
    """ماتریس کامل و خودکار نقاط پایانی (ضد درفت مستندات)."""
    lines = [
        "# ماتریس کامل نقاط پایانی API نسخهٔ ۱ (تولیدشدهٔ خودکار)",
        "",
        "> این جدول مستقیماً از [`openapi.yaml`](../api/v1/openapi.yaml) ساخته شده است. "
        "هرگونه تغییر مسیر، متد یا پارامتر بدون بازتولید این فایل توسط CI رد میشود.",
        "",
        f"- تعداد مسیرها: **{len(doc['paths'])}**",
        f"- تعداد عملیاتها: **{len(ops)}**",
        f"- تعداد اسکیماها: **{len(doc['components']['schemas'])}**",
        f"- تعداد تگها: **{len(doc.get('tags', []))}**",
        "- سرورها: " + ", ".join("`" + s["url"] + "`" for s in doc.get("servers", [])),
        "",
        "| متد | مسیر | operationId | احراز هویت | خلاصه |",
        "| --- | --- | --- | --- | --- |",
    ]
    auth_labels = {"none": "عمومی", "optional": "اختیاری", "required": "الزامی"}
    for row in ops:
        auth = auth_labels.get(row["policy"].get("auth", "required"), "الزامی")
        lines.append(
            f"| `{row['method']}` | `{row['path']}` | `{row['operationId']}` | {auth} | "
            f"{row['summary'].replace('|', '\\|')} |"
        )
    lines.extend(
        [
            "",
            "## پارامترهای پرکاربرد",
            "",
            "| مسیر | پارامتر | محل | الزامی |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in ops:
        for p in row["parameters"]:
            if p.get("in") in {"query", "path"}:
                lines.append(
                    f"| `{row['path']}` | `{p['name']}` | {p['in']} | "
                    f"{'بله' if p.get('required') else 'خیر'} |"
                )
    lines.extend(
        ["", "---", "", "بازتولید: `python scripts/build_frontend_kit.py` یا `make handoff`.", ""]
    )
    return "\n".join(lines)


def build_errors_md(problem_codes: list[tuple[str, int, str, str, str]]) -> str:
    """کاتالوگ خطاها با لنگرهای پایدار متناظر با فیلد type در RFC 9457."""
    lines = [
        "# کاتالوگ رسمی خطاهای API (RFC 9457) — ویژهٔ فرانتاند",
        "",
        "> هر پاسخ خطا `Content-Type: application/problem+json` دارد و فیلد `type` آن "
        "دقیقاً به یکی از لنگرهای زیر اشاره میکند. مبنای branching در رابط کاربری، "
        "**`code`** است؛ هرگز روی `detail` یا `status` بهتنهایی شرط نگذارید.",
        "",
        "## شکل کلی پاسخ خطا",
        "",
        "```json",
        "{",
        '  "type": "https://github.com/mohebbibrothers/Crowdfunding-Back/blob/main/docs/frontend/ERRORS.md#error-mfa_required",',
        '  "title": "تأیید دومرحلهای الزامی است",',
        '  "status": 403,',
        '  "detail": "برای دسترسی به پنل عملیاتی، ابتدا کد تأیید دومرحلهای را وارد کنید.",',
        '  "code": "mfa_required",',
        '  "instance": "/api/v1/contributions/checkout",',
        '  "trace_id": "019384ab-...",',
        '  "errors": { "shares_count": ["باید بزرگتر از صفر باشد."] }',
        "}",
        "```",
        "",
        "## فهرست کدها",
        "",
        "| کد (`code`) | HTTP | عنوان | اقدام پیشنهادی در رابط |",
        "| --- | --- | --- | --- |",
    ]
    for code, status, title, _detail, action in problem_codes:
        lines.append(
            f"| [`{code}`](#error-{code}) | `{status}` | {title} | {action.replace('|', '\\|')} |"
        )
    lines.extend(["", "## جزئیات هر کد", ""])
    for code, status, title, detail, action in problem_codes:
        lines.extend(
            [
                f'### <a id="error-{code}"></a>`{code}` — {title} (`{status}`)',
                "",
                f"- **شرح سرور:** {detail}",
                f"- **اقدام فرانتاند:** {action}",
                f"- **نشانی `type`:** `.../ERRORS.md#error-{code}`",
                "",
            ]
        )
    lines.extend(
        [
            "## قواعد سراسری مدیریت خطا",
            "",
            "1. همیشه `trace_id` (معادل هدر `X-Request-ID`) را در پیام پشتیبانی نمایش دهید.",
            "2. برای `429` و `503` تنها پس از `Retry-After` / `retry_after` و با backoff نمایی تلاش مجدد کنید.",
            "3. `422` را با نگاشت `errors[field]` مستقیماً پایین همان فیلدها نشان دهید.",
            "4. `403` با `code=mfa_required` یا `step_up_required` یعنی بازکردن مودال TOTP و "
            "سپس **بازارسال همان درخواست با همان `Idempotency-Key`**.",
            "5. `401` یعنی یکبار `POST /api/v1/auth/token/refresh`؛ در صورت شکست، پاکسازی کامل "
            "توکنها و هدایت به جریان OTP (هرگز حلقهٔ بیپایان refresh نسازید).",
            "",
        ]
    )
    return "\n".join(lines)


# ─── Portal ───────────────────────────────────────────────────────────────────


def sync_portal(
    doc: dict[str, Any], ops: list[dict[str, Any]], codes: list[tuple[Any, ...]]
) -> None:
    """تزریق دادهها و آمار زنده به کاوشگر آفلاین index.html (همگام با قرارداد)."""
    portal = OUT / "index.html"
    if not portal.is_file():
        return
    compact = [
        {
            "method": row["method"],
            "path": row["path"],
            "id": row["operationId"],
            "summary": row["summary"],
            "tag": row["tags"][0],
        }
        for row in ops
    ]
    payload = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    meta = {
        "paths": len(doc["paths"]),
        "operations": len(ops),
        "schemas": len(doc["components"]["schemas"]),
        "problem_codes": len(codes),
    }
    text = portal.read_text(encoding="utf-8")
    patched, n = re.subn(
        r"/\* DATA_START \*/.*?/\* DATA_END \*/",
        "/* DATA_START */\n" + payload + "\n/* DATA_END */",
        text,
        count=1,
        flags=re.DOTALL,
    )
    assert n == 1, "portal data markers not found"
    patched, n = re.subn(
        r"/\* META_START \*/.*?/\* META_END \*/",
        "/* META_START */ const META = "
        + json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
        + "; /* META_END */",
        patched,
        count=1,
        flags=re.DOTALL,
    )
    assert n == 1, "portal meta markers not found"
    portal.write_text(patched, encoding="utf-8")


# ─── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    """تولید تمام داراییها و چاپ خلاصهٔ فارسی."""
    doc = load_schema()
    ops = operations(doc)
    problem_codes = load_problem_codes()
    OUT.mkdir(parents=True, exist_ok=True)

    raw = SCHEMA_PATH.read_bytes()
    fingerprint = {
        "source": "docs/api/v1/openapi.yaml",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "openapi": doc["openapi"],
        "paths": len(doc["paths"]),
        "operations": len(ops),
        "schemas": len(doc["components"]["schemas"]),
        "tags": len(doc.get("tags", [])),
        "problem_codes": len(problem_codes),
        "generator": "scripts/build_frontend_kit.py",
    }

    (OUT / "ENDPOINTS.md").write_text(build_endpoints_md(doc, ops), encoding="utf-8")
    (OUT / "ERRORS.md").write_text(build_errors_md(problem_codes), encoding="utf-8")
    (OUT / "api-types.d.ts").write_text(build_types(doc, ops), encoding="utf-8")
    (OUT / "operations.ts").write_text(build_operations_ts(ops), encoding="utf-8")
    (OUT / "postman_collection.json").write_text(
        json.dumps(build_postman(doc, ops), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (OUT / "contract-fingerprint.json").write_text(
        json.dumps(fingerprint, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    sync_portal(doc, ops, problem_codes)
    print(
        f"بستهٔ فرانتاند بازتولید شد: {len(ops)} عملیات، "
        f"{len(doc['components']['schemas'])} اسکیما، {len(problem_codes)} کد خطا."
    )
    print(f"اثر انگشت قرارداد: {fingerprint['sha256'][:16]}…")


if __name__ == "__main__":
    main()
