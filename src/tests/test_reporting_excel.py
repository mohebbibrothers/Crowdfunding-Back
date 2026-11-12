"""آزمون‌های موتور اکسل مدیریتی ۸ کاربرگه (RTL، A4 Landscape، نمودار، ضد Formula-Injection، SHA-256 و Step-Up MFA)."""

from __future__ import annotations

import hashlib
from io import BytesIO

import openpyxl
import pytest

from apps.campaigns.models import Campaign
from apps.contributions.services import initiate_contribution_checkout, verify_payment_callback
from apps.identity.models import User
from apps.reporting.excel import sanitize_spreadsheet_cell
from apps.reporting.models import ReportExportLog
from tests.conftest import issue_client_for_user

EXPECTED_SHEETS = [
    "خلاصه مدیریتی",
    "حرکت‌ها",
    "خیریه‌ها و قلک‌ها",
    "پرداخت‌های درگاه",
    "مشارکت‌ها و نیت‌نامه‌ها",
    "مشارکت‌های خارجی",
    "تسویه‌ها و دفترکل",
    "مغایرت‌گیری و اصالت",
]


def test_spreadsheet_formula_injection_and_bidi_sanitizer() -> None:
    """خنثی‌سازی فرمول‌های مخرب اکسل (=, +, -, @) و حذف کاراکترهای مخفی BiDi/کنترلی."""
    assert str(sanitize_spreadsheet_cell("=CMD|' /C calc'!A0")).startswith("'=")
    assert str(sanitize_spreadsheet_cell("+SUM(A1:A5)")).startswith("'+")
    assert str(sanitize_spreadsheet_cell("-10+20")).startswith("'-")
    assert str(sanitize_spreadsheet_cell("@IMPORTXML()")).startswith("'@")
    assert "\u202e" not in str(sanitize_spreadsheet_cell("متن\u202eامن"))


@pytest.mark.django_db
def test_8_sheet_rtl_excel_workbook_sha256_chart_and_step_up_mfa_privacy(
    active_campaign: Campaign,
    donor_user: User,
    finance_user: User,
) -> None:
    """تولید اکسل ۸ کاربرگه راست‌به‌چپ با نمودار ستونی، هدر X-Document-SHA256، خنثی‌سازی فرمول و گیت MFA."""
    _, payment = initiate_contribution_checkout(
        user=donor_user,
        target_kind="campaign_shares",
        campaign_id=str(active_campaign.id),
        shares_count=4,
        public_note='=HYPERLINK("https://evil.example","کلیک")',
    )
    verify_payment_callback(authority=payment.authority, gateway_status="OK")

    fin_fresh_client, _ = issue_client_for_user(finance_user, mfa_fresh=True)

    # ۱. دریافت فایل اکسل بدون شماره کامل (پوشانده‌شده پیش‌فرض) + تطابق دقیق SHA-256
    exp_masked = fin_fresh_client.get("/api/v1/admin/reports/excel")
    assert exp_masked.status_code == 200
    xlsx_bytes = exp_masked.content
    expected_sha = hashlib.sha256(xlsx_bytes).hexdigest()
    assert exp_masked["X-Document-SHA256"] == expected_sha

    wb = openpyxl.load_workbook(BytesIO(xlsx_bytes))
    assert wb.sheetnames == EXPECTED_SHEETS

    for ws in wb.worksheets:
        assert ws.sheet_view.rightToLeft is True
        assert ws.page_setup.orientation == ws.ORIENTATION_LANDSCAPE
        assert str(ws.page_setup.paperSize) == str(ws.PAPERSIZE_A4)

    # کاربرگ ۱ (خلاصه مدیریتی) دارای نمودار ستونی توکار (BarChart) است
    ws_summary = wb["خلاصه مدیریتی"]
    assert len(ws_summary._charts) >= 1

    # کاربرگ ۴ (پرداخت‌های درگاه): شماره موبایل خیر پوشانده است
    ws_payments = wb["پرداخت‌های درگاه"]
    sheet4_values = [
        str(cell.value or "") for row in ws_payments.iter_rows(min_row=4) for cell in row
    ]
    assert donor_user.phone not in sheet4_values
    assert any("*" in v for v in sheet4_values)

    # کاربرگ ۵ (مشارکت‌ها و نیت‌نامه‌ها): هرگونه فرمول مخرب خنثی شده است
    ws_contribs = wb["مشارکت‌ها و نیت‌نامه‌ها"]
    sheet5_values = [
        str(cell.value or "") for row in ws_contribs.iter_rows(min_row=4) for cell in row
    ]
    assert not any(v.startswith("=HYPERLINK") for v in sheet5_values)

    # ۲. درخواست شماره‌های کامل بدون دلیل اداری باید با خطای ۴۲۲ رد شود
    bad_raw = fin_fresh_client.get("/api/v1/admin/reports/excel?include_raw_phones=true")
    assert bad_raw.status_code == 422

    # ۳. درخواست شماره‌های کامل با MFA تازه و ثبت دلیل رسمی -> موفق و ثبت در ReportExportLog
    raw_ok = fin_fresh_client.get(
        "/api/v1/admin/reports/excel",
        data={
            "include_raw_phones": "true",
            "reason": "تهیه لیست تماس تقدیر سالانه خیرین",
        },
    )
    assert raw_ok.status_code == 200
    wb_raw = openpyxl.load_workbook(BytesIO(raw_ok.content))
    raw_values = [
        str(cell.value or "")
        for row in wb_raw["پرداخت‌های درگاه"].iter_rows(min_row=4)
        for cell in row
    ]
    assert donor_user.phone in raw_values
    assert ReportExportLog.objects.filter(include_raw_phones=True).count() == 1

    hist = fin_fresh_client.get("/api/v1/admin/reports/exports-history")
    assert hist.status_code == 200
    h_json = hist.json()
    h_items = h_json["results"] if isinstance(h_json, dict) else h_json
    assert len(h_items) >= 2
