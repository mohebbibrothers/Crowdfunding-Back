"""گیتهای تحویل فرانتاند: همگامی قرارداد، مستندات، تایپها، خطاها و مسیرهای زنده."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any

from django.conf import settings
from django.test import RequestFactory, override_settings
from django.urls import resolve
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "api" / "v1" / "openapi.yaml"
FRONTEND_DIR = REPO_ROOT / "docs" / "frontend"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
DOC_ONLY_PATHS = {
    "/api/v1",
    "/api/v1/docs",
    "/api/v1/redoc",
    "/api/v1/schema",
    "/api/v1/openapi.yaml",
    "/api/v1/readme.md",
    "/api/v1/README.md",
    "/api/v1/admin",
    "/metrics",
}

# مستنداتی که در اسکن درفت مسیرها بررسی میشوند (غیر از اسکیما و فایلهای تولیدی)
MARKDOWN_FILES = sorted(
    p
    for p in REPO_ROOT.rglob("*.md")
    if ".venv" not in p.parts and ".git" not in p.parts and "node_modules" not in p.parts
)


def _schema() -> dict[str, object]:
    return yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))


def _operations(doc: dict[str, object]) -> list[tuple[str, str, dict[str, object]]]:
    paths = doc["paths"]
    assert isinstance(paths, dict)
    result: list[tuple[str, str, dict[str, object]]] = []
    for path, item in paths.items():
        assert isinstance(item, dict)
        for method, spec in item.items():
            if method in HTTP_METHODS:
                assert isinstance(spec, dict)
                result.append((str(path), str(method), spec))
    return result


def _normalize(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "<x>", path).rstrip("/")


def _generator_module() -> object:
    """بارگذاری اسکریپت تولید بسته، بدون اجرای main و بدون اثر جانبی."""
    spec = importlib.util.spec_from_file_location(
        "frontend_kit_builder", REPO_ROOT / "scripts" / "build_frontend_kit.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ─── قرارداد ─────────────────────────────────────────────────────────────────


def test_contract_declares_servers_tags_and_problem_schema() -> None:
    """قرارداد باید سرورها، تگهای توضیحدار و اسکیمای خطای RFC 9457 داشته باشد."""
    doc = _schema()
    assert str(doc["openapi"]).startswith("3.1.")
    assert str(doc["info"]["version"]).startswith("1.1.0")
    assert "app_version" in doc["components"]["schemas"]["PlatformMeta"]["properties"]
    assert len(doc["servers"]) >= 1  # type: ignore[arg-type]
    assert doc["externalDocs"]["url"].startswith("https://")  # type: ignore[index]
    assert len(doc["tags"]) == len(  # type: ignore[arg-type]
        {tag for _, _, op in _operations(doc) for tag in op["tags"]}  # type: ignore[index]
    )
    problem = doc["components"]["schemas"]["Problem"]  # type: ignore[index]
    for field in ("type", "title", "status", "detail", "code", "instance", "trace_id"):
        assert field in problem["required"]
    assert len(problem["properties"]["code"]["enum"]) >= 38


def test_every_operation_documents_standard_problem_errors() -> None:
    """تمام ۸۳ عملیات باید پاسخهای خطای قابل بازاستفاده و هدر ردیابی داشته باشند."""
    doc = _schema()
    expected = {"400", "401", "403", "404", "405", "409", "410", "422", "429", "500", "503"}
    for path, method, op in _operations(doc):
        responses = op["responses"]
        assert isinstance(responses, dict)
        assert expected <= {str(k) for k in responses}, f"{method.upper()} {path}"
        for status in expected:
            declared = responses[status]
            # 503 سلامت سرویس اسکیمای اختصاصی خود را دارد؛ بقیه به Problem ارجاع میدهند.
            assert "$ref" in declared or declared.get("content"), (
                f"{method.upper()} {path} {status}"
            )
            if "$ref" in declared:
                assert declared["$ref"].startswith("#/components/responses/Problem")
        headers = {p.get("name") for p in op.get("parameters", [])}
        assert "X-Request-ID" in headers, f"missing trace header on {path}"
        assert op["x-frontend-policy"]["errorFormat"] == "application/problem+json"
        assert op["x-frontend-policy"]["auth"] in {"none", "optional", "required"}
    assert len(_operations(doc)) == 83
    assert len(doc["paths"]) == 72  # type: ignore[arg-type]


def test_no_untyped_success_responses() -> None:
    """هیچ پاسخ موفقی نباید object/array بدون اسکیمای تایپشده باشد."""
    doc = _schema()
    offenders: list[str] = []
    for path, method, op in _operations(doc):
        for status, response in op["responses"].items():  # type: ignore[union-attr]
            if not str(status).startswith("2") or "$ref" in response:
                continue
            for media in response.get("content", {}).values():
                sub = media.get("schema", {})
                if sub.get("type") == "object" and "properties" not in sub:
                    offenders.append(f"{method.upper()} {path} {status}: object")
                if sub.get("type") == "array" and sub.get("items", {}).get("type") == "object":
                    offenders.append(f"{method.upper()} {path} {status}: array")
                if sub.get("$ref"):
                    continue
    assert not offenders, "Untyped success responses:\n" + "\n".join(offenders)


def test_paginated_endpoints_have_envelope_and_cursor() -> None:
    """پنج لیست مکاننمایی باید پوشش {results, meta} و پارامتر cursor اعلام کنند."""
    doc = _schema()
    targets = {
        "/api/v1/me/contributions": "PaginatedContributionUser",
        "/api/v1/me/notifications": "PaginatedUserNotification",
        "/api/v1/admin/audit/logs": "PaginatedAuditRecord",
        "/api/v1/admin/users": "PaginatedAdminUser",
        "/api/v1/admin/auth/risk-signals": "PaginatedAuthRiskSignal",
    }
    paths = doc["paths"]
    assert isinstance(paths, dict)
    for path, expected_schema in targets.items():
        op = paths[path]["get"]
        params = {p["name"] for p in op["parameters"]}
        assert "cursor" in params and "page_size" in params, path
        ref = op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith(expected_schema), path
        env = doc["components"]["schemas"][expected_schema]  # type: ignore[index]
        assert set(env["required"]) == {"results", "meta"}
        assert op["x-frontend-policy"]["paginated"] is True


def test_security_schemes_match_runtime_settings() -> None:
    """نام کوکی مستندشده دقیقاً باید همان نام کوکی واقعی جنگو باشد."""
    from apps.identity.jwt_auth import (
        SessionAwareCookieAuthentication,
        SessionAwareCookieScheme,
    )

    doc = _schema()
    schemes = doc["components"]["securitySchemes"]  # type: ignore[index]
    assert schemes["bearerAuth"]["scheme"] == "bearer"
    assert schemes["cookieAuth"]["name"] == settings.SESSION_COOKIE_NAME
    assert schemes["csrfToken"]["name"] == "X-CSRFToken"
    scheme = SessionAwareCookieScheme(SessionAwareCookieAuthentication)
    assert scheme.get_security_definition(None)["name"] == settings.SESSION_COOKIE_NAME
    assert settings.SESSION_COOKIE_NAME == settings.AUTH_SESSION_COOKIE_NAME
    assert settings.APP_VERSION == "1.1.0"


# ─── درفت مستندات ────────────────────────────────────────────────────────────


def test_no_stale_endpoint_references_in_markdown() -> None:
    """هیچ سند نثر نباید مسیر/متدی را معرفی کند که در قرارداد وجود ندارد."""
    doc = _schema()
    known_paths = {_normalize(str(p)) for p in doc["paths"]}
    known_methods: dict[str, set[str]] = {}
    for path, method, _spec in _operations(doc):
        known_methods.setdefault(_normalize(path), set()).add(method.upper())
    allowed = {_normalize(p) for p in DOC_ONLY_PATHS}
    path_re = re.compile(r"/api/v1/[A-Za-z0-9_\-/{}\.]+")
    table_re = re.compile(
        r"^\|\s*`(GET|POST|PATCH|PUT|DELETE)`\s*\|\s*`(/api/v1/[^`]+)`\s*\|", re.MULTILINE
    )
    offenders: list[str] = []
    for md in MARKDOWN_FILES:
        text = md.read_text(encoding="utf-8")
        rel = md.relative_to(REPO_ROOT)
        for match in path_re.finditer(text):
            raw = match.group(0).rstrip("/.,):؛»")
            norm = _normalize(raw)
            if norm in known_paths or norm in allowed:
                continue
            offenders.append(f"{rel}: unknown path {raw}")
        for method, raw in table_re.findall(text):
            norm = _normalize(raw)
            if norm in known_methods and method not in known_methods[norm]:
                offenders.append(f"{rel}: {method} not allowed on {raw}")
    assert not offenders, "Documentation drift:\n" + "\n".join(offenders)


def test_documentation_references_real_frontend_assets() -> None:
    """تمام پیوندهای بستهٔ فرانتاند به فایلهای موجود اشاره کنند."""
    required = {
        "index.html",
        "HANDOFF.md",
        "CHECKLIST.md",
        "README.md",
        "api-client.ts",
        "api-types.d.ts",
        "operations.ts",
        "type-tests.ts",
        "tsconfig.json",
        "ENDPOINTS.md",
        "ERRORS.md",
        "postman_collection.json",
        "contract-fingerprint.json",
    }
    existing = {p.name for p in FRONTEND_DIR.iterdir() if p.is_file()}
    assert required <= existing, f"Missing: {sorted(required - existing)}"


# ─── همگامی داراییهای تولیدشده ──────────────────────────────────────────────


def test_generated_frontend_assets_are_in_sync() -> None:
    """بازتولید در حافظه باید بایت به بایت با فایلهای commitشده یکسان باشد."""
    gen = _generator_module()
    doc = gen.load_schema()  # type: ignore[attr-defined]
    ops = gen.operations(doc)  # type: ignore[attr-defined]
    codes = gen.load_problem_codes()  # type: ignore[attr-defined]
    expected = {
        "ENDPOINTS.md": gen.build_endpoints_md(doc, ops),  # type: ignore[attr-defined]
        "ERRORS.md": gen.build_errors_md(codes),  # type: ignore[attr-defined]
        "api-types.d.ts": gen.build_types(doc, ops),  # type: ignore[attr-defined]
        "operations.ts": gen.build_operations_ts(ops),  # type: ignore[attr-defined]
        "postman_collection.json": json.dumps(
            gen.build_postman(doc, ops),  # type: ignore[attr-defined]
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    }
    for name, content in expected.items():
        assert (FRONTEND_DIR / name).read_text(encoding="utf-8") == content, f"Stale: {name}"

    payload = json.loads((FRONTEND_DIR / "contract-fingerprint.json").read_text(encoding="utf-8"))
    assert payload["sha256"] == hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()
    assert payload["operations"] == len(ops) == 83
    assert payload["schemas"] == len(doc["components"]["schemas"])
    assert payload["problem_codes"] == len(codes)


def test_portal_explorer_contains_every_operation() -> None:
    """کاوشگر آفلاین پورتال باید دقیقاً ۸۳ عملیات زنده داشته باشد."""
    text = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    assert "cdn." not in text.lower() and "https://fonts." not in text, "portal must be offline"
    match = re.search(r"/\* DATA_START \*/\s*(.*?)\s*/\* DATA_END \*/", text, re.DOTALL)
    assert match is not None
    rows = json.loads(match.group(1))
    doc = _schema()
    live = {(str(p), m.upper()) for p, m, _ in _operations(doc)}
    embedded = {(r["path"], r["method"]) for r in rows}
    assert embedded == live
    assert all(r["id"] and r["summary"] and r["tag"] for r in rows)


def test_postman_collection_covers_all_operations() -> None:
    """کالکشن Postman باید ۸۳ درخواست و متغیرهای موردنیاز را داشته باشد."""
    collection = json.loads((FRONTEND_DIR / "postman_collection.json").read_text(encoding="utf-8"))
    requests = [item for folder in collection["item"] for item in folder["item"]]
    assert len(requests) == 83
    assert {v["key"] for v in collection["variable"]} == {
        "baseUrl",
        "accessToken",
        "csrfToken",
    }
    bodies = [r["request"]["body"] for r in requests if "body" in r["request"]]
    assert any("shares_count" in b["raw"] for b in bodies)


# ─── رفتار زنده سرور ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_docs_routes_are_live_and_well_named(client: object) -> None:
    """مسیرهای schema / Swagger / ReDoc باید وجود داشته باشند و ۲۰۰ بدهند."""
    for path, name in (
        ("/api/v1/schema", "v1-openapi-schema"),
        ("/api/v1/docs", "v1-swagger-ui"),
        ("/api/v1/redoc", "v1-redoc"),
    ):
        assert resolve(path).url_name == name
    with override_settings(API_DOCS_ALLOW_ANONYMOUS=True):
        for path in ("/api/v1/schema", "/api/v1/docs", "/api/v1/redoc"):
            response = client.get(path)  # type: ignore[attr-defined]
            assert response.status_code == 200, f"{path}: {response.status_code}"


def test_docs_csp_allows_official_cdn_but_apis_stay_strict() -> None:
    """CSP صفحات مستندات باید CDN مجاز را آزاد کند و سایر مسیرها سخت بمانند."""
    from apps.core.middleware import SecurityAndCacheHeadersMiddleware

    def _ok(request: object) -> object:
        from django.http import HttpResponse

        return HttpResponse("ok")

    middleware = SecurityAndCacheHeadersMiddleware(_ok)  # type: ignore[arg-type]
    factory = RequestFactory()
    docs = middleware(factory.get("/api/v1/docs"))
    api = middleware(factory.get("/api/v1/meta"))
    assert "cdn.jsdelivr.net" in docs["Content-Security-Policy"]
    assert "cdn.jsdelivr.net" not in api["Content-Security-Policy"]


def test_every_throttle_scope_has_a_configured_rate() -> None:
    """هیچ محدودکنندهای نباید بدون نرخ تعریفشده رها شود (خطای زمان اجرا)."""
    from apps.identity import throttles

    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    scopes = {
        cls.scope
        for cls in (
            throttles.StandardIpThrottle,
            throttles.CheckoutThrottle,
            throttles.OtpRequestThrottle,
            throttles.OtpVerifyThrottle,
            throttles.MfaVerifyThrottle,
        )
    }
    assert scopes <= set(rates)
    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] == [
        "apps.identity.throttles.StandardIpThrottle"
    ]


def test_problem_type_uri_points_to_real_docs_anchor() -> None:
    """تمام ۳۸ کد خطا باید لنگر واقعی در کاتالوگ فرانت‌اند داشته باشند."""
    from apps.core.problems import problem_type_uri
    from apps.core.schema import PROBLEM_CODES

    errors_md = (FRONTEND_DIR / "ERRORS.md").read_text(encoding="utf-8")
    anchors = set(re.findall(r'id="(error-[^"]+)"', errors_md))
    codes = {row[0] for row in PROBLEM_CODES}
    assert len(codes) == 38
    assert anchors == {f"error-{code}" for code in codes}
    for code in codes:
        assert problem_type_uri(code).endswith(f"ERRORS.md#error-{code}")
    # هیچ واژهٔ بیگانه/نیمهنوشته در عناوین و شرحهای کاربرمحور باقی نماند.
    prose = " ".join(row[2] + " " + row[3] + " " + row[4] for row in PROBLEM_CODES)
    assert "exceeded" not in prose
    assert not re.search(r"[\u4e00-\u9fff]", prose)


def test_contract_enrichment_hook_is_idempotent() -> None:
    """هوک تقویت قرارداد باید بایدار و بدون تکرار پارامتر در دو بار اجرا باشد."""
    from apps.core.schema import enrich_contract_schema

    sample = {
        "openapi": "3.1.0",
        "paths": {
            "/x": {
                "get": {"operationId": "v1_auth_otp_request", "responses": {"200": {}}},
                "post": {
                    "operationId": "v1_auth_otp_request",
                    "responses": {"200": {}},
                    "requestBody": {"content": {"application/json": {"schema": {}}}},
                },
            }
        },
    }
    from copy import deepcopy

    once = enrich_contract_schema(deepcopy(sample), None, None, True)
    before = deepcopy(once)
    twice = enrich_contract_schema(deepcopy(once), None, None, True)
    assert once == before == twice
    assert "Problem" in once["components"]["schemas"]
    assert len(once["components"]["responses"]) == 11
    post_op = once["paths"]["/x"]["post"]
    headers = {p["name"] for p in post_op["parameters"]}
    assert {"X-Request-ID", "Idempotency-Key", "X-CSRFToken"} <= headers
    assert "If-None-Match" not in headers
    assert "examples" in post_op["requestBody"]["content"]["application/json"]
    assert post_op["x-frontend-policy"]["retry"] == "idempotency-key"


def test_paginated_response_helper_builds_envelope() -> None:
    """سازندهٔ پوشش صفحهبندی باید results و meta با گزینهٔ total بسازد."""
    from rest_framework import serializers

    from apps.core.schema import paginated_response

    class _Item(serializers.Serializer):
        name = serializers.CharField()

    plain = paginated_response(_Item, name="PlainPage")
    with_total = paginated_response(_Item, name="TotalPage", include_total=True)
    assert set(plain.fields) == {"results", "meta"}
    assert "total" in with_total.fields["meta"].fields
    assert "total" not in plain.fields["meta"].fields


# ─── گیتهای تکمیلی نسخهٔ ۱٫۱٫۰: معنا، مثال، پیوند و نگاشت ──────────────────


def test_public_operations_declare_no_security() -> None:
    """عملیات عمومی باید صریحاً security: [] داشته باشند، نه [{}] مبهم."""
    doc = _schema()
    count = 0
    for _path, _method, op in _operations(doc):
        if op["x-frontend-policy"]["auth"] == "none":
            assert op.get("security") == [], f"{op['operationId']}: security must be []"
            count += 1
    assert count == 18


def test_operations_map_matches_typed_union() -> None:
    """نگاشت operations.ts و اتحادیهٔ ApiOperationId دقیقاً یک مجموعه باشند."""
    types_text = (FRONTEND_DIR / "api-types.d.ts").read_text(encoding="utf-8")
    ops_text = (FRONTEND_DIR / "operations.ts").read_text(encoding="utf-8")
    union_ids = set(re.findall(r'"(v1_[a-z0-9_]+)"', types_text))
    map_ids = set(re.findall(r'^\s*"(v1_[^"]+)":', ops_text, re.MULTILINE))
    assert union_ids == map_ids
    assert len(map_ids) == 83
    assert "ApiOperationMap" in types_text and "ApiOperationId" in types_text


def test_request_body_examples_use_valid_enums() -> None:
    """نمونههای بدنهٔ درخواست باید مقادیر مجاز enumها را استفاده کنند (درس 422 زودهنگام)."""
    doc = _schema()
    schemas = doc["components"]["schemas"]

    def enum_for(prop: Any) -> set[Any] | None:
        if not isinstance(prop, dict):
            return None
        if "enum" in prop:
            return set(prop["enum"])
        refs = [prop["$ref"]] if "$ref" in prop else []
        refs += [
            sub["$ref"] for sub in prop.get("allOf", []) if isinstance(sub, dict) and "$ref" in sub
        ]
        for ref in refs:
            name = str(ref).rsplit("/", 1)[-1]
            if name in schemas and "enum" in schemas[name]:
                return set(schemas[name]["enum"])
        return None

    checked = 0
    for path, method, op in _operations(doc):
        body = op.get("requestBody")
        if not isinstance(body, dict):
            continue
        for media in body.get("content", {}).values():
            schema_ref = media.get("schema", {}).get("$ref", "")
            name = str(schema_ref).rsplit("/", 1)[-1]
            if name not in schemas:
                continue
            constraints = {
                key: values
                for key, prop in schemas[name].get("properties", {}).items()
                if (values := enum_for(prop)) is not None
            }
            for example in media.get("examples", {}).values():
                value = example.get("value")
                if not isinstance(value, dict):
                    continue
                for key, allowed in constraints.items():
                    if key in value:
                        checked += 1
                        assert value[key] in allowed, (
                            f"{method.upper()} {path}: {key}={value[key]!r}, "
                            f"allowed={sorted(allowed)}"
                        )
    assert checked >= 3


def test_markdown_links_resolve() -> None:
    """هیچ پیوند نسبی شکستهای در کل مستندات مخزن وجود نداشته باشد."""
    link = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
    broken: list[str] = []
    for md in MARKDOWN_FILES:
        content = md.read_text(encoding="utf-8")
        assert not any(line.rstrip(" \t") != line for line in content.splitlines()), (
            f"{md.relative_to(REPO_ROOT)}: trailing whitespace"
        )
        for match in link.finditer(content):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#", "data:")):
                continue
            clean = target.split("#", 1)[0].split("?", 1)[0]
            if clean and not (md.parent / clean).resolve().exists():
                broken.append(f"{md.relative_to(REPO_ROOT)} → {target}")
    assert not broken, "Broken markdown links:\n" + "\n".join(broken)


def test_handoff_shorthand_paths_match_contract() -> None:
    """مسیرهای کوتاهنوشتهٔ راهنما (مثلاً GET /campaigns) باید در قرارداد وجود داشته باشند."""
    doc = _schema()
    known = {_normalize(str(path)) for path in doc["paths"]}
    shorthand = re.compile(
        r"`(?:(?:GET|POST|PATCH|PUT|DELETE)"
        r"(?:\|(?:GET|POST|PATCH|PUT|DELETE))?\s+)?(/[^`\s]+)`"
    )
    allowed = {"/", "/login", "/metrics", "/my-app", "/src/api"}
    offenders: list[str] = []
    for md in MARKDOWN_FILES:
        for match in shorthand.finditer(md.read_text(encoding="utf-8")):
            raw_full = match.group(1)
            if "..." in raw_full:
                continue
            raw = raw_full.split("?", 1)[0].split("#", 1)[0].rstrip("/.,):؛»")
            if raw.startswith("/api/v1") or raw in allowed or raw.startswith("/cdn"):
                continue
            if _normalize("/api/v1" + raw) not in known:
                offenders.append(f"{md.relative_to(REPO_ROOT)} → {raw}")
    assert not offenders, "Shorthand path drift:\n" + "\n".join(offenders)


def test_portal_links_meta_and_javascript_are_valid() -> None:
    """پورتال آفلاین: پیوندها سالم، آمار زنده و JavaScript از نظر نحوی معتبر باشد."""
    doc = _schema()
    from apps.core.schema import PROBLEM_CODES

    text = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    for href in re.findall(r'href="([^"]+)"', text):
        if href.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = href.split("#", 1)[0]
        assert (FRONTEND_DIR / target).resolve().exists(), f"broken portal link: {href}"

    meta_match = re.search(
        r"/\* META_START \*/ const META = (\{.*?\}); /\* META_END \*/",
        text,
        re.DOTALL,
    )
    assert meta_match is not None
    meta = json.loads(meta_match.group(1))
    assert meta == {
        "paths": len(doc["paths"]),
        "operations": len(_operations(doc)),
        "schemas": len(doc["components"]["schemas"]),
        "problem_codes": len(PROBLEM_CODES),
    }

    scripts = re.findall(r"<script>(.*?)</script>", text, re.DOTALL)
    assert len(scripts) >= 1
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js در محیط اجرای تست موجود نیست؛ گیت CI آن را اجرا میکند.")
    with tempfile.TemporaryDirectory() as tmp:
        for index, body in enumerate(scripts):
            script_path = Path(tmp) / f"portal-{index}.js"
            script_path.write_text(body, encoding="utf-8")
            result = subprocess.run(  # noqa: S603
                [node, "--check", str(script_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr


def test_portal_quality_stats_match_test_suite() -> None:
    """عدد تستهای پورتال با تعداد واقعی توابع test در مخزن همخوان باشد."""
    count = 0
    for test_file in (REPO_ROOT / "src" / "tests").glob("test_*.py"):
        tree = ast.parse(test_file.read_text(encoding="utf-8"))
        count += sum(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
            for node in tree.body
        )
    text = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    assert f"{count}/{count}" in text, f"Portal still advertises stale test count ({count})"
    coverage = re.search(r"<b>(\d{2}\.\d{2})%</b>", text)
    assert coverage is not None and float(coverage.group(1)) >= 85


# ─── گیت‌های ممیزی زندهٔ نسخهٔ ۱٫۱٫۰ (تایپ تاریخ، CSRF، پیام فارسی) ─────────


def test_typescript_types_match_runtime_json_scalars() -> None:
    """هر فیلد date-time در قرارداد باید در api-types.d.ts رشته باشد (نه epoch).

    رگرسیون واقعی: مولد پیش‌تر ``format: date-time`` را به ``number`` نگاشت می‌کرد
    در حالی که DRF مقدار ``2026-11-14T10:53:28+03:30`` برمی‌گرداند؛ یعنی فرانت
    روی ``new Date(number)`` بی‌صدا تاریخ ۱۹۷۰ نشان می‌داد.
    """
    doc = _schema()
    schemas = doc["components"]["schemas"]
    types_text = (FRONTEND_DIR / "api-types.d.ts").read_text(encoding="utf-8")
    interfaces = dict(re.findall(r"export interface (\w+) \{ (.*?) \}", types_text, re.DOTALL))
    offenders: list[str] = []
    for name, body in interfaces.items():
        spec = schemas.get(name, {})
        for field, decl in re.findall(r"(\w+)\??: ([^;]+);", body):
            prop = spec.get("properties", {}).get(field)
            if not prop:
                continue
            rtype = prop.get("type")
            kinds = rtype if isinstance(rtype, list) else [rtype]
            if (
                "string" in kinds
                and prop.get("format") in {"date-time", "date"}
                and "number" in decl
            ):
                offenders.append(f"{name}.{field}: {decl.strip()}")
            if prop.get("format") == "binary" and decl.strip() not in {"Blob", "(Blob | null)"}:
                offenders.append(f"{name}.{field}: binary → {decl.strip()}")
    assert not offenders, "Type/runtime drift:\n" + "\n".join(offenders)


def test_every_problem_code_has_persian_prose() -> None:
    """هر کد خطا باید عنوان/شرح/اقدام فارسی داشته باشد و هیچ واژهٔ لاتین نشت نکند."""
    from apps.core.schema import PROBLEM_CODES

    latin_word = re.compile(r"\b(?:CSRF Failed|Authentication credentials|Not found|Bad Request)\b")
    for code, status, title, description, action in PROBLEM_CODES:
        assert re.fullmatch(r"[a-z0-9_]+", code), code
        assert 400 <= status <= 599, code
        for text in (title, description, action):
            assert re.search(r"[\u0600-\u06FF]", text), f"{code}: non-Persian text {text!r}"
            assert not latin_word.search(text), f"{code}: leaked English phrase in {text!r}"


def test_csrf_failure_maps_to_dedicated_problem_code() -> None:
    """خطای CSRF باید ``csrf_failed`` باشد تا کلاینت بتواند بی‌صدا توکن را تازه کند."""
    from apps.core.problems import custom_exception_handler

    class _Req:
        path = "/api/v1/me"
        trace_id = "trace-csrf"

    exc = __import__("rest_framework.exceptions", fromlist=["PermissionDenied"]).PermissionDenied(
        "CSRF Failed: CSRF token from the 'X-CSRFToken' HTTP header has incorrect length."
    )
    response = custom_exception_handler(exc, {"request": _Req()})
    assert response is not None
    assert response.status_code == 403
    payload = response.data
    assert payload["code"] == "csrf_failed"
    assert "csrf" not in str(payload["detail"]).lower()
    assert re.search(r"[\u0600-\u06FF]", str(payload["detail"]))


def test_auth_failures_never_leak_english_drf_messages() -> None:
    """پیام‌های انگلیسی DRF («Authentication credentials were not provided») نشت نکند."""
    from rest_framework.exceptions import NotAuthenticated

    from apps.core.problems import custom_exception_handler

    class _Req:
        path = "/api/v1/me"
        trace_id = "trace-auth"

    exc = NotAuthenticated("Authentication credentials were not provided.")
    response = custom_exception_handler(exc, {"request": _Req()})
    assert response is not None and response.status_code == 401
    assert response.data["code"] == "authentication_required"
    assert "Authentication credentials" not in str(response.data["detail"])


def test_frontend_client_recovers_from_csrf_rotation() -> None:
    """کلاینت مرورگری باید پس از ورود، توکن CSRF تازه بگیرد و درخواست را تکرار کند."""
    client_text = (FRONTEND_DIR / "api-client.ts").read_text(encoding="utf-8")
    for marker in (
        "isCsrfExpired",
        "csrfRetried",
        'cache: "no-store"',
        "resetCsrf",
    ):
        assert marker in client_text, f"api-client.ts missing: {marker}"
    assert 'problem.isCsrfExpired && options.authMode === "cookie" && !csrfRetried' in client_text


def test_meta_today_jalali_matches_documented_format() -> None:
    """قالب ``today_jalali`` در کد و مستند یکسان باشد (YYYY-MM-DD با خط تیره)."""
    from apps.core.jalali import today_jalali

    value = today_jalali()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), value
    handoff = (FRONTEND_DIR / "HANDOFF.md").read_text(encoding="utf-8")
    assert '"today_jalali": "' in handoff
    documented = re.search(r'"today_jalali": "([^"]+)"', handoff)
    assert documented is not None
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", documented.group(1)), documented.group(1)
