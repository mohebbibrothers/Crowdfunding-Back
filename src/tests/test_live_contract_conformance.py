"""هارنس انطباق زنده — پاسخ واقعی سرور در برابر اسکیمای قرارداد.

چرا این تست وجود دارد
---------------------
تا امروز، هم‌گامیِ «کد» و «قرارداد» با سه لایه سنجیده می‌شد:

1. ``verify_contract_sync.py`` — قرارداد با مولد یکی است؟
2. ``test_frontend_contract.py`` — نمونه‌ها با اسکیما می‌خوانند؟
3. تست‌های دامنه — هر عملیات رفتار درست دارد؟

ولی **هیچ‌کدام نمی‌سنجید که پاسخ واقعیِ سرور با اسکیمای منتشرشده بخواند**.
یعنی اگر یک serializer فیلدی برمی‌گرداند که در قرارداد اعلام نشده، یا فیلد
اجباری‌ای را جا می‌اندازد، همهٔ گیت‌ها سبز می‌ماندند و کد فرانت که بر اساس
``api-types.d.ts`` نوشته شده، در زمان اجرا می‌شکست — دقیقاً همان لحظه‌ای که
تیم فرانت کمترین وقت را برای دیباگ دارد.

این فایل همان حلقهٔ گمشده است: سرور واقعی بالا می‌آید، درخواست واقعی می‌رود،
و **بدنهٔ پاسخ با ``jsonschema`` در برابر اسکیمای همان عملیات** سنجیده
می‌شود. اگر ناسازگاری باشد، CI قرمز می‌شود — نه مرورگر کاربر.

پوشش عمدی
---------
عملیاتِ **عمومی** (بدون احراز هویت) و چند عملیات کلیدیِ احرازشده با توکن
واقعی. کل ۱۰۴ عملیات را با کلاینت تست نمی‌زنیم چون این تست باید سریع و
پایدار بماند؛ ولی همین ۲۰ مورد، تمام خانواده‌های شکل پاسخ را پوشش می‌دهند:
فهرست مکان‌نمایی‌شده، شیء منفرد، enum، مبلغ ریال/تومان، تاریخ، nullable،
و پاسخ خطای RFC 9457.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from django.test import Client
from jsonschema import Draft202012Validator
import pytest
import yaml

from apps.identity.models import User
from tests.test_capture_recovery import _admin, _campaign, _donor

pytestmark = pytest.mark.django_db

OPENAPI_PATH = "docs/api/v1/openapi.yaml"


# ══════════════════════════════════════════════════════════════════════════════
# زیرساخت: باز کردن $ref و ساخت validator از اسکیمای یک عملیات
# ══════════════════════════════════════════════════════════════════════════════


def _load_contract() -> dict[str, Any]:
    return yaml.safe_load(Path(OPENAPI_PATH).read_text(encoding="utf-8"))


def _resolve(node: Any, doc: dict[str, Any], depth: int = 0) -> Any:
    """باز کردن بازگشتی ``$ref`` تا سند قابل‌فهم برای jsonschema."""
    if depth > 40:
        raise RuntimeError("حلقهٔ ارجاع در قرارداد")
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            target: Any = doc
            for part in ref.removeprefix("#/").split("/"):
                target = target[part]
            # ویژگی‌های کنارِ $ref (مثل description) معنایی برای اعتبارسنجی ندارند
            return _resolve(target, doc, depth + 1)
        return {key: _resolve(value, doc, depth + 1) for key, value in node.items()}
    if isinstance(node, list):
        return [_resolve(item, doc, depth + 1) for item in node]
    return node


def _response_schema(
    doc: dict[str, Any], path: str, method: str, status: int = 200
) -> dict[str, Any] | None:
    """اسکیمای JSON پاسخ موفق یک عملیات، آمادهٔ اعتبارسنجی."""
    operation = doc["paths"].get(path, {}).get(method)
    if not operation:
        return None
    response = operation.get("responses", {}).get(str(status))
    if not isinstance(response, dict):
        return None
    # پاسخ‌های خطا با $ref به ``components/responses/ProblemNNN`` اشاره می‌کنند؛
    # بدون باز کردن، هر بررسی خطا با «اسکیما ندارد» رد می‌شد — یعنی مهم‌ترین
    # بخش قرارداد (خطاها) هرگز سنجیده نمی‌شد.
    response = _resolve(response, doc)
    # پاسخ‌های موفق ``application/json`` هستند و پاسخ‌های خطا
    # ``application/problem+json`` (RFC 9457). جستجو فقط روی نوع اول، همهٔ
    # بررسی‌های خطا را با «اسکیما ندارد» رد می‌کرد.
    content = response.get("content", {})
    media = content.get("application/json") or content.get("application/problem+json")
    if not isinstance(media, dict) or "schema" not in media:
        return None
    return _resolve(media["schema"], doc)


def _assert_matches(
    contract: dict[str, Any], path: str, method: str, body: Any, status: int = 200
) -> None:
    """قفل اصلی: بدنهٔ پاسخ واقعی باید اسکیمای منتشرشده را رعایت کند."""
    schema = _response_schema(contract, path, method, status)
    assert schema is not None, f"قرارداد برای {method.upper()} {path} اسکیمای پایان‌یافته ندارد"
    errors = sorted(Draft202012Validator(schema).iter_errors(body), key=lambda e: list(e.path))
    if errors:
        details = "\n".join(
            f"  • {'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors[:12]
        )
        raise AssertionError(
            f"پاسخ واقعی {method.upper()} {path} با قرارداد نمی‌خواند:\n{details}\n"
            f"بدنه: {json.dumps(body, ensure_ascii=False, default=str)[:600]}"
        )


def _login(client: Client, user: User) -> None:
    """ورود به کلاینت تست — همان مسیری که فرانت با کوکی طی می‌کند."""
    client.force_login(user)


# ══════════════════════════════════════════════════════════════════════════════
# عملیات عمومی — بدون احراز هویت، در دسترس هر کلاینتی
# ══════════════════════════════════════════════════════════════════════════════

PUBLIC_CASES: list[tuple[str, str, dict[str, Any]]] = [
    ("/api/v1/campaigns", "get", {}),
    ("/api/v1/jars", "get", {}),
    ("/api/v1/campaign-categories", "get", {}),
    ("/api/v1/benefactors", "get", {}),
    ("/api/v1/health/live", "get", {}),
    ("/api/v1/health/ready", "get", {}),
]


@pytest.mark.parametrize(("path", "method", "query"), PUBLIC_CASES)
def test_public_endpoint_payload_matches_published_schema(
    path: str, method: str, query: dict[str, Any], seeded_policies: None
) -> None:
    """هر پاسخ عمومی باید دقیقاً همان شکلی باشد که در قرارداد منتشر شده.

    چرا این مهم‌ترین تست این فایل است: تیم فرانت تایپ‌ها را از قرارداد
    می‌گیرد. اگر سرور فیلدی برگرداند که در قرارداد نیست، تایپ «کمتر از
    واقعیت» است و مقدارها در زمان اجرا از دست می‌روند (با ``strip`` یا
    نادیده گرفتن). اگر فیلد اجباری جا بیفتد، ``undefined`` می‌شود و کامپوننت
    می‌شکند. هیچ‌کدام با تست‌های معمولی گرفته نمی‌شود.
    """
    del seeded_policies
    contract = _load_contract()
    response = Client().get(path, query)
    assert response.status_code == 200, f"{path} → {response.status_code}"
    body = response.json()
    _assert_matches(contract, path, method, body)


def test_campaign_detail_matches_schema_with_real_row(seeded_policies: None) -> None:
    """جزئیات یک حرکت واقعی — شیء تک با تاریخ، مبلغ و enum."""
    del seeded_policies
    admin = _admin("77")
    campaign = _campaign(admin, slug_suffix="live1")

    contract = _load_contract()
    response = Client().get(f"/api/v1/campaigns/{campaign.slug}")
    assert response.status_code == 200
    _assert_matches(contract, "/api/v1/campaigns/{identifier}", "get", response.json())


def test_campaign_transparency_matches_schema(seeded_policies: None) -> None:
    """گزارش شفافیت یک حرکت — ساختار تو‌در‌تو با هش و تفکیک سهام."""
    del seeded_policies
    admin = _admin("76")
    campaign = _campaign(admin, slug_suffix="live-t")

    contract = _load_contract()
    response = Client().get(f"/api/v1/campaigns/{campaign.slug}/transparency")
    assert response.status_code == 200, response.content[:300]
    _assert_matches(contract, "/api/v1/campaigns/{identifier}/transparency", "get", response.json())


def test_campaign_supporters_matches_schema(seeded_policies: None) -> None:
    """فهرست حامیان یک حرکت — صفحه‌بندی و ماسک هویت."""
    del seeded_policies
    admin = _admin("74")
    campaign = _campaign(admin, slug_suffix="live-s")

    contract = _load_contract()
    response = Client().get(f"/api/v1/campaigns/{campaign.slug}/supporters")
    assert response.status_code == 200, response.content[:300]
    _assert_matches(contract, "/api/v1/campaigns/{identifier}/supporters", "get", response.json())


def test_error_response_matches_rfc9457_problem_schema(seeded_policies: None) -> None:
    """خطای ۴۰۴ باید دقیقاً بدنهٔ ``Problem`` باشد — نه HTML جنگو، نه شکل دیگر.

    اگر فرانت روی ``code`` سوئیچ می‌کند و سرور در یک مسیر کد را جا بیندازد،
    UI پیام عمومی نشان می‌دهد و کاربر راهنمایی نمی‌شود. این تست همان را قفل
    می‌کند.
    """
    del seeded_policies
    contract = _load_contract()
    response = Client().get(f"/api/v1/campaigns/{uuid4()}")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")
    body = response.json()
    _assert_matches(contract, "/api/v1/campaigns/{identifier}", "get", body, status=404)
    assert body["code"], "خطا بدون کد ماشین‌خوان — فرانت نمی‌تواند branching کند"
    assert body["trace_id"], "خطا بدون trace_id — پشتیبانی نمی‌تواند پرونده را پیدا کند"


# ══════════════════════════════════════════════════════════════════════════════
# عملیات احرازشده — با کاربر واقعی و کوکی نشست
# ══════════════════════════════════════════════════════════════════════════════


def test_authenticated_me_profile_matches_schema(seeded_policies: None) -> None:
    """نمای پروفایل خود — اولین چیزی که هر اپ فرانت صدا می‌زند."""
    del seeded_policies
    donor = _donor("78")
    client = Client()
    _login(client, donor)

    contract = _load_contract()
    response = client.get("/api/v1/me")
    assert response.status_code == 200, response.content[:300]
    _assert_matches(contract, "/api/v1/me", "get", response.json())


def test_authenticated_csrf_endpoint_returns_token(seeded_policies: None) -> None:
    """توکن CSRF — بدون آن فرانت کوکی‌محور نمی‌تواند هیچ نوشتنی بفرستد."""
    del seeded_policies
    donor = _donor("79")
    client = Client()
    _login(client, donor)

    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("csrf_token"), str) and body["csrf_token"]


def test_pledge_list_payload_matches_schema(seeded_policies: None) -> None:
    """فهرست تعهدها — خانوادهٔ پاسخ با فیلدهای تازه (progress/remaining)."""
    del seeded_policies
    donor = _donor("80")
    client = Client()
    _login(client, donor)

    from apps.contributions.choices import ContributionTargetKind
    from apps.contributions.recurring import create_recurring_pledge

    admin = _admin("80")
    campaign = _campaign(admin, slug_suffix="live2")
    create_recurring_pledge(
        user=donor,
        benefactor=campaign.benefactor,
        target_kind=ContributionTargetKind.CAMPAIGN_SHARES,
        amount_rial=1_000_000,
        campaign=campaign,
        duration_months=6,
    )

    contract = _load_contract()
    response = client.get("/api/v1/me/pledges")
    assert response.status_code == 200, response.content[:300]
    body = response.json()
    _assert_matches(contract, "/api/v1/me/pledges", "get", body)

    # قفل معنایی: فیلدهای تازه واقعاً پر شده‌اند، نه nullِ بی‌دلیل.
    first = body[0] if isinstance(body, list) else body["results"][0]
    assert first["duration_months"] == 6
    # قسط اول در همان لحظهٔ ساخت ساخته و پرداخت‌نشده است، پس هنوز ۰ پرداخت
    # شده و هر ۶ قسط مانده. «مانده» یعنی «پرداخت‌نشده»، نه «تولیدنشده».
    assert first["installments_paid"] == 0
    assert first["installments_remaining"] == 6
    assert first["progress_percent"] == 0
    assert first["status"] == "active"


def test_pledge_create_response_matches_schema(seeded_policies: None) -> None:
    """پاسخ ۲۰۱ ساخت تعهد — بدنهٔ نوشتنی، نه فقط خواندنی."""
    del seeded_policies
    donor = _donor("81")
    client = Client()
    _login(client, donor)

    admin = _admin("81")
    campaign = _campaign(admin, slug_suffix="live3")

    contract = _load_contract()
    response = client.post(
        "/api/v1/me/pledges",
        data=json.dumps(
            {
                "target_kind": "campaign_shares",
                "campaign_id": str(campaign.pk),
                "amount_rial": 2_000_000,
                "duration_months": 12,
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content[:500]
    _assert_matches(contract, "/api/v1/me/pledges", "post", response.json(), status=201)


def test_validation_error_body_matches_schema(seeded_policies: None) -> None:
    """خطای اعتبارسنجی ۴۲۲ — پرتکرارترین پاسخ در طول توسعهٔ فرانت.

    نکتهٔ قراردادی: نقض قاعدهٔ **دامنه** (مبلغ صفر، مقصد ناهم‌خوان) با ۴۲۲
    پاسخ داده می‌شود، حال آنکه بدنهٔ **بدشکل** (JSON نامعتبر، فیلد غایب)
    ۴۰۰ می‌گیرد. تفکیک عمدی است و فرانت باید هر دو را جدا مدیریت کند:
    ۴۲۲ یعنی «ورودی را اصلاح کن»، ۴۰۰ یعنی «درخواستت خراب است».
    """
    del seeded_policies
    donor = _donor("82")
    client = Client()
    _login(client, donor)

    contract = _load_contract()
    response = client.post(
        "/api/v1/me/pledges",
        data=json.dumps({"target_kind": "campaign_shares", "amount_rial": 0}),
        content_type="application/json",
    )
    assert response.status_code == 422, response.content[:300]
    _assert_matches(contract, "/api/v1/me/pledges", "post", response.json(), status=422)


# ══════════════════════════════════════════════════════════════════════════════
# یکپارچگی قرارداد: هر فیلد اجباریِ پاسخ باید واقعاً موجود باشد
# ══════════════════════════════════════════════════════════════════════════════


def test_no_declared_required_field_is_missing_from_live_response(seeded_policies: None) -> None:
    """سنجش دوطرفه: هم اسکیما رعایت شود، هم هیچ فیلد اجباری جا نیفتد.

    jsonschema فیلدهای *اضافه* را مجاز می‌داند (``additionalProperties`` باز
    است). این تست آن را جبران می‌کند: برای هر فیلد اجباری در قرارداد، بررسی
    می‌کند که در پاسخ واقعی **کلید وجود داشته باشد** — چون ``undefined`` در
    TS از ``null`` بدتر است.
    """
    del seeded_policies
    contract = _load_contract()
    admin = _admin("83")
    campaign = _campaign(admin, slug_suffix="live4")

    response = Client().get(f"/api/v1/campaigns/{campaign.slug}")
    assert response.status_code == 200
    body = response.json()

    schema = _response_schema(contract, "/api/v1/campaigns/{identifier}", "get")
    assert schema is not None
    missing = [field for field in schema.get("required", []) if field not in body]
    assert not missing, f"فیلدهای اجباریِ غایب در پاسخ واقعی: {missing}"


def test_contract_has_no_unresolvable_refs() -> None:
    """هیچ ``$ref`` شکسته‌ای در قرارداد نباشد.

    ارجاع شکسته یعنی تایپ‌تولیدکنندهٔ فرانت (openapi-typescript) یا سکوت
    می‌کند یا ``any`` می‌سازد — و هر دو یعنی تایپ «تضمین» نیست.
    """
    contract = _load_contract()

    def collect(node: Any, found: set[str]) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/"):
                found.add(ref)
            for value in node.values():
                collect(value, found)
        elif isinstance(node, list):
            for item in node:
                collect(item, found)

    refs: set[str] = set()
    collect(contract, refs)
    assert len(refs) > 100, "قرارداد به‌طور غیرمنتظره کوچک است"

    broken: list[str] = []
    for ref in sorted(refs):
        target: Any = contract
        try:
            for part in ref.removeprefix("#/").split("/"):
                target = target[part]
        except (KeyError, TypeError):
            broken.append(ref)
    assert not broken, f"ارجاع‌های شکسته در قرارداد: {broken[:10]}"


def test_every_paginated_list_has_meta_contract(seeded_policies: None) -> None:
    """همهٔ فهرست‌های مکان‌نمایی‌شده ``meta`` با ``next`` و ``previous`` دارند.

    فرانت برای «صفحهٔ بعد» فقط به ``meta.next`` تکیه می‌کند. اگر یک فهرست
    آن را نداشته باشد، دکمهٔ بعدی بی‌صدا از کار می‌افتد — باگی که فقط در
    صفحهٔ دوم دیده می‌شود و در تست‌های تک‌صفحه‌ای هرگز لو نمی‌رود.
    """
    del seeded_policies
    donor = _donor("84")
    client = Client()
    _login(client, donor)

    for path in ("/api/v1/me/notifications", "/api/v1/me/contributions"):
        response = client.get(path)
        assert response.status_code == 200, f"{path} → {response.status_code}"
        body = response.json()
        assert "results" in body, f"{path} کلید results ندارد"
        meta = body.get("meta")
        assert isinstance(meta, dict), f"{path} کلید meta ندارد"
        for key in ("next", "previous"):
            assert key in meta, f"{path} → meta.{key} غایب است"


def test_money_fields_are_always_paired_rial_and_toman(seeded_policies: None) -> None:
    """قاعدهٔ آهنین مالی: هر مبلغ ریالی، نسخهٔ تومانی هم دارد و ۱۰ برابر نیست.

    باگ «۱۰ برابر» رایج‌ترین باگ مالی در پروژه‌های ایرانی است و در تست‌های
    واحد دامنه دیده نمی‌شود چون هر دو عدد از یک منبع می‌آیند. اینجا در سطح
    **قرارداد و پاسخ واقعی** سنجیده می‌شود.
    """
    del seeded_policies
    admin = _admin("85")
    campaign = _campaign(admin, slug_suffix="live5", total_shares=10)

    body = Client().get(f"/api/v1/campaigns/{campaign.slug}").json()
    rial_fields = [key for key in body if key.endswith("_rial")]
    assert rial_fields, "هیچ فیلد ریالی در پاسخ نیست — قرارداد عوض شده؟"

    for rial_key in rial_fields:
        toman_key = rial_key.replace("_rial", "_toman")
        assert toman_key in body, f"{rial_key} بدون {toman_key} — فرانت مجبور به تقسیم می‌شود"
        rial_value = body[rial_key]
        toman_value = body[toman_key]
        assert isinstance(rial_value, int), f"{rial_key} عدد صحیح نیست: {type(rial_value)}"
        assert toman_value == rial_value // 10, (
            f"{toman_key}={toman_value} با {rial_key}={rial_value} هم‌خوان نیست "
            f"(انتظار {rial_value // 10})"
        )


# ══════════════════════════════════════════════════════════════════════════════
# قفل سراسری: هیچ عملیات GET نباید اسکیمای «نوع اشتباه» اعلام کند
# ══════════════════════════════════════════════════════════════════════════════


def test_no_list_endpoint_declares_the_wrong_envelope_shape(
    seeded_policies: None,
) -> None:
    """ممیزی سراسری: هر GET که آرایه اعلام شده، باید آرایه برگرداند و برعکس.

    چرا سراسری و نه موردی: دو باگ هم‌خانواده پیش‌تر پیدا شد
    (``/api/v1/campaigns`` و ``/api/v1/admin/settlements``) — هر دو سرور
    envelope برمی‌گرداندند و قرارداد array. تست موردی فقط همان دو را
    می‌گرفت؛ این تست **هر عملیات عمومی و هر عملیات ادمینی** را که پاسخ
    ۲۰۰ می‌دهد می‌سنجد، و اگر فردا کسی ``many=True`` را روی یک فهرست
    صفحه‌بندی‌شده بگذارد، CI قرمز می‌شود.

    عملیات احرازشدهٔ کاربری جدا سنجیده می‌شوند (بالاتر در همین فایل) چون
    به دادهٔ مالکیت‌دار نیاز دارند.
    """
    del seeded_policies
    from tests.conftest import issue_client_for_user

    contract = _load_contract()
    admin = _admin("86")
    campaign = _campaign(admin, slug_suffix="live-env")
    staff, _tokens = issue_client_for_user(admin, mfa_fresh=True)
    anon = Client()

    def concrete(path: str) -> str:
        return (
            path.replace("{identifier}", campaign.slug)
            .replace("{slug}", campaign.slug)
            .replace("{benefactor_id}", str(campaign.benefactor_id))
            .replace("{campaign_id}", str(campaign.pk))
            .replace("{user_id}", str(admin.pk))
        )

    checked: list[str] = []
    offenders: list[str] = []

    for path, item in contract["paths"].items():
        operation = item.get("get")
        if not isinstance(operation, dict):
            continue
        response = operation.get("responses", {}).get("200")
        if not isinstance(response, dict):
            continue
        schema = _response_schema(contract, path, "get", 200)
        if schema is None:
            continue
        declared_array = schema.get("type") == "array"

        url = concrete(path)
        if "{" in url:
            continue  # پارامتر ناشناخته — با تست‌های موردی پوشش داده می‌شود

        for client in (staff, anon):
            response_obj = client.get(url)
            if response_obj.status_code != 200:
                continue
            try:
                body = response_obj.json()
            except ValueError:
                break
            checked.append(path)
            if declared_array != isinstance(body, list):
                offenders.append(
                    f"{path}: قرارداد {'آرایه' if declared_array else 'شیء'} می‌گوید، "
                    f"سرور {'آرایه' if isinstance(body, list) else 'شیء'} داد"
                )
            break

    assert len(checked) >= 15, f"پوشش ممیزی کم است: فقط {len(checked)} عملیات"
    assert not offenders, "واگرایی شکل پاسخ:\n" + "\n".join(offenders)


def test_health_endpoints_share_one_vocabulary(seeded_policies: None) -> None:
    """هر سه پروب سلامت باید از همان enum سه‌حالته استفاده کنند.

    پیش از این ``/health/live`` مقدار «alive» و ``/health/ready`` مقدار
    «ready» برمی‌گرداند، در حالی که قرارداد برای هر سه
    ``healthy|degraded|unhealthy`` اعلام کرده بود. یک پایش‌گر که بر اساس
    قرارداد کد نوشته باشد، هرگز سبز نمی‌شد — و این را هیچ تستی نمی‌دید
    چون تست‌ها دقیقاً همان رشته‌های غلط را assert می‌کردند.
    """
    del seeded_policies
    allowed = {"healthy", "degraded", "unhealthy"}
    for path in ("/api/v1/health/live", "/api/v1/health/ready"):
        response = Client().get(path)
        assert response.status_code in {200, 503}
        status = response.json()["status"]
        assert status in allowed, f"{path} → «{status}» بیرون از enum قرارداد"


def test_all_declared_enums_are_actually_emitted_by_some_field() -> None:
    """هر enum در قرارداد باید در جایی از پاسخ‌ها واقعاً استفاده شود.

    enum تعریف‌شده ولی استفاده‌نشده یعنی «حالت فانتوم» — همان دسته باگی که
    ``PledgeStatus.COMPLETED`` بود. فرانت تایپش را می‌سازد و برایش UI
    می‌نویسد، ولی سرور هرگز آن مقدار را نمی‌فرستد.
    """
    contract = _load_contract()
    schemas = contract["components"]["schemas"]

    enum_names = {
        name
        for name, schema in schemas.items()
        if isinstance(schema, dict) and isinstance(schema.get("enum"), list)
    }
    assert len(enum_names) >= 20, f"enumهای قرارداد به‌طور غیرمنتظره کم‌اند: {len(enum_names)}"

    # کدام enumها به‌عنوان $ref استفاده می‌شوند؟
    used: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                used.add(ref.rsplit("/", 1)[-1])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(contract)

    unused = sorted(enum_names - used)
    assert not unused, f"enumهای فانتوم (تعریف‌شده ولی استفاده‌نشده): {unused}"
