"""گیت‌های انضباط معماری (AST DAG، لایه‌بندی بدون ORM مستقیم در ویو، OpenAPI 3.1 و مهاجرت‌ها)."""

from __future__ import annotations

import ast
from io import StringIO
from pathlib import Path

from django.core.management import call_command
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
APPS_DIR = REPO_ROOT / "src" / "apps"

# ترتیب اکید DAG وابستگی ۹ دامنه (فقط ارجاع به لایه‌های پایین‌تر مجاز است)
DAG_ORDER: list[str] = [
    "core",
    "audit",
    "identity",
    "notifications",
    "benefactors",
    "campaigns",
    "ledger",
    "contributions",
    "reporting",
]
DAG_INDEX: dict[str, int] = {name: idx for idx, name in enumerate(DAG_ORDER)}

FORBIDDEN_VIEW_ATTRS: set[str] = {"save", "delete", "hard_delete", "bulk_create", "bulk_update"}


def _extract_imported_apps(py_file: Path) -> set[tuple[str, int]]:
    """استخراج نام اپ‌های واردشده از طریق ``import apps.X`` یا ``from apps.X import ...``."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    found: set[tuple[str, int]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if len(parts) >= 2 and parts[0] == "apps" and parts[1] in DAG_INDEX:
                    found.add((parts[1], node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if len(parts) >= 2 and parts[0] == "apps" and parts[1] in DAG_INDEX:
                found.add((parts[1], node.lineno))
    return found


DOMAIN_MODULE_NAMES: set[str] = {
    "models.py",
    "choices.py",
    "validators.py",
    "services.py",
    "selectors.py",
    "serializers.py",
}


def test_bounded_context_acyclic_dag_discipline() -> None:
    """هستهٔ دامنه‌ای و داده‌ای هر ۹ اپ باید اکیداً از DAG پیروی کند و گراف کل ماژول‌ها صفر چرخه داشته باشد."""
    violations: list[str] = []
    module_edges: dict[str, set[str]] = {}

    for app_name, app_rank in DAG_INDEX.items():
        app_path = APPS_DIR / app_name
        assert app_path.is_dir(), f"Missing bounded context directory: {app_name}"
        for py_file in app_path.rglob("*.py"):
            if "migrations" in py_file.parts or "management" in py_file.parts:
                continue
            mod_name = ".".join(py_file.relative_to(REPO_ROOT / "src").with_suffix("").parts)
            module_edges.setdefault(mod_name, set())

            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("apps."):
                            module_edges[mod_name].add(alias.name)
                elif (
                    isinstance(node, ast.ImportFrom)
                    and node.module
                    and node.module.startswith("apps.")
                ):
                    module_edges[mod_name].add(node.module)

            if py_file.name in DOMAIN_MODULE_NAMES:
                for target_app, lineno in _extract_imported_apps(py_file):
                    target_rank = DAG_INDEX[target_app]
                    if target_rank > app_rank:
                        rel = py_file.relative_to(REPO_ROOT)
                        violations.append(
                            f"{rel}:{lineno} ({app_name} [rank {app_rank}] imports higher app {target_app} [rank {target_rank}])"
                        )

    assert not violations, "Domain DAG dependency violations detected:\n" + "\n".join(violations)

    # راستی‌آزمایی نبود هیچ‌گونه دور (Cycle) در گراف کامل ماژول‌های هر ۹ اپ با DFS سه‌رنگ
    state: dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=done

    def _dfs(node: str, trail: list[str]) -> None:
        state[node] = 1
        for nxt in module_edges.get(node, set()):
            if nxt == node or nxt not in module_edges:
                continue
            st_nxt = state.get(nxt, 0)
            assert st_nxt != 1, f"Import cycle detected: {' -> '.join([*trail, nxt])}"
            if st_nxt == 0:
                _dfs(nxt, [*trail, nxt])
        state[node] = 2

    for mod in list(module_edges):
        if state.get(mod, 0) == 0:
            _dfs(mod, [mod])


def test_thin_views_never_mutate_models_directly() -> None:
    """هیچ فایل ``views.py`` نباید متدهای تغییر مستقیم مدل (save/delete/bulk_create) را صدا بزند."""
    violations: list[str] = []
    for views_file in APPS_DIR.glob("*/views.py"):
        tree = ast.parse(views_file.read_text(encoding="utf-8"), filename=str(views_file))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in FORBIDDEN_VIEW_ATTRS
            ):
                rel = views_file.relative_to(REPO_ROOT)
                violations.append(
                    f"{rel}:{node.lineno} calls .{node.func.attr}() directly in views.py"
                )
    assert not violations, "Layer discipline violations in views.py:\n" + "\n".join(violations)


@pytest.mark.django_db
def test_migrations_have_zero_uncommitted_drift() -> None:
    """مهاجرت‌های موجود دقیقاً با وضعیت فعلی مدل‌ها هم‌تراز هستند."""
    out = StringIO()
    call_command("makemigrations", "--check", "--dry-run", stdout=out)
    assert "No changes detected" in out.getvalue()


def test_openapi_31_schema_is_valid_and_in_sync() -> None:
    """اسکیمای OpenAPI 3.1 بدون هیچ هشدار یا خطایی تولید شده و با فایل مخزن یکسان است."""
    schema_path = REPO_ROOT / "docs" / "api" / "v1" / "openapi.yaml"
    assert schema_path.is_file(), "docs/api/v1/openapi.yaml must exist"

    committed_doc = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    assert committed_doc["openapi"].startswith("3.1.")
    paths = committed_doc.get("paths", {})
    assert "/api/v1/meta" in paths
    assert "/api/v1/campaigns" in paths
    assert "/api/v1/contributions/checkout" in paths
    assert "/api/v1/contributions/express/start" in paths
    assert "/api/v1/me/dashboard" in paths
    assert "/api/v1/admin/reports/excel" in paths

    # هر عملیات در مسیرهای v1 باید دارای operationId یکتا باشد
    seen_ops: set[str] = set()
    for path_key, methods in paths.items():
        for http_method, spec in methods.items():
            if http_method.lower() in {"get", "post", "put", "patch", "delete"}:
                op_id = spec.get("operationId")
                assert op_id, f"Missing operationId on {http_method.upper()} {path_key}"
                assert op_id not in seen_ops, f"Duplicate operationId: {op_id}"
                seen_ops.add(op_id)
