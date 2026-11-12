"""موتور تولید کتابچهٔ اکسل اجرایی ۸ کاربرگهٔ فارسی (RTL، چاپ A4 افقی، نمودار، ایمن در برابر تزریق فرمول و تکرارپذیر بایتی)."""

from __future__ import annotations

from datetime import datetime
import hashlib
import io
import re
from typing import Any
import zipfile

from django.db.models import Sum
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from apps.benefactors.models import Benefactor, CharityJar
from apps.campaigns.models import Campaign
from apps.contributions.choices import ContributionStatus
from apps.contributions.models import Contribution, ExternalContribution, Payment
from apps.core.crypto import mask_phone
from apps.core.jalali import format_jalali_datetime
from apps.core.money import rial_to_toman
from apps.ledger.choices import ReconciliationItemStatus
from apps.ledger.models import (
    DisbursementRequest,
    LedgerAccount,
    LedgerPosting,
    ReconciliationItem,
)
from apps.ledger.services import get_benefactor_payable_balance_rial

_BIDI_OVERRIDE_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069]")
_DANGEROUS_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

FONT_FAMILY = "Tahoma"
HEADER_FILL = PatternFill(start_color="0F3D3E", end_color="0F3D3E", fill_type="solid")
SUBHEADER_FILL = PatternFill(start_color="1B5E20", end_color="1B5E20", fill_type="solid")
ZEBRA_FILL = PatternFill(start_color="F4F8F7", end_color="F4F8F7", fill_type="solid")
TOTAL_FILL = PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid")
ALERT_FILL = PatternFill(start_color="FFEBEE", end_color="FFEBEE", fill_type="solid")

TITLE_FONT = Font(name=FONT_FAMILY, size=13, bold=True, color="FFFFFF")
HEADER_FONT = Font(name=FONT_FAMILY, size=10, bold=True, color="FFFFFF")
BODY_FONT = Font(name=FONT_FAMILY, size=10, bold=False, color="1E293B")
BOLD_FONT = Font(name=FONT_FAMILY, size=10, bold=True, color="0F172A")

THIN_SIDE = Side(border_style="thin", color="CBD5E1")
CELL_BORDER = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)
ALIGN_RTL = Alignment(horizontal="right", vertical="center", wrap_text=True, readingOrder=2)
ALIGN_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True, readingOrder=2)
NUMBER_FMT_INT = "#,##0"


def sanitize_spreadsheet_cell(value: Any) -> Any:
    """پاک‌سازی کامل کاراکترهای BiDi مخرب و خنثی‌سازی تزریق فرمول اکسل (CSV/XLSX Formula Injection)."""
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = _BIDI_OVERRIDE_RE.sub("", str(value))
    if text.startswith(_DANGEROUS_FORMULA_PREFIXES):
        return f"'{text}"
    return text


def _configure_rtl_print_sheet(ws: Worksheet, *, title_banner: str, col_widths: list[int]) -> None:
    """تنظیم راست‌به‌چپ، بنر عنوان، عرض ستون‌ها و صفحه‌بندی چاپ A4 افقی در هر کاربرگ."""
    ws.sheet_view.rightToLeft = True
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    max_col = max(1, len(col_widths))
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max_col)
    banner_cell = ws.cell(row=1, column=1, value=sanitize_spreadsheet_cell(title_banner))
    banner_cell.font = TITLE_FONT
    banner_cell.fill = HEADER_FILL
    banner_cell.alignment = ALIGN_CENTER
    ws.row_dimensions[1].height = 30

    for idx, width in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width


def _write_table_headers(ws: Worksheet, *, header_row: int, headers: list[str]) -> None:
    """نوشتن سطر سرستون‌های جدول و قفل کردن پنل بالایی (Freeze Panes)."""
    ws.row_dimensions[header_row].height = 24
    for col_idx, text in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=sanitize_spreadsheet_cell(text))
        cell.font = HEADER_FONT
        cell.fill = SUBHEADER_FILL
        cell.alignment = ALIGN_CENTER
        cell.border = CELL_BORDER
    ws.freeze_panes = f"A{header_row + 1}"


def _write_data_row(
    ws: Worksheet,
    *,
    row_idx: int,
    values: list[Any],
    money_cols: set[int] | None = None,
    highlight_alert: bool = False,
) -> None:
    """نوشتن یک سطر داده با قالب‌بندی عددی هزارگان، زبرا و پاک‌سازی امنیتی سلول‌ها."""
    ws.row_dimensions[row_idx].height = 20
    money_cols = money_cols or set()
    fill = ALERT_FILL if highlight_alert else (ZEBRA_FILL if row_idx % 2 == 1 else None)

    for col_idx, raw_val in enumerate(values, start=1):
        val = sanitize_spreadsheet_cell(raw_val)
        cell = ws.cell(row=row_idx, column=col_idx, value=val)
        cell.font = BODY_FONT
        cell.border = CELL_BORDER
        cell.alignment = ALIGN_RTL if isinstance(val, str) else ALIGN_CENTER
        if fill is not None:
            cell.fill = fill
        if col_idx in money_cols and isinstance(val, int):
            cell.number_format = NUMBER_FMT_INT


def _canonicalize_xlsx_bytes(raw_xlsx: bytes) -> bytes:
    """استانداردسازی زمان فایل‌های درون آرشیو ZIP برای تولید خروجی بایت‌به‌بایت تکرارپذیر."""
    src_buf = io.BytesIO(raw_xlsx)
    dst_buf = io.BytesIO()
    fixed_dt = (2026, 1, 1, 0, 0, 0)

    with (
        zipfile.ZipFile(src_buf, "r") as zin,
        zipfile.ZipFile(dst_buf, "w", compression=zipfile.ZIP_DEFLATED) as zout,
    ):
        for name in sorted(zin.namelist()):
            content = zin.read(name)
            # پاک‌سازی تاریخ ساخت متغیر در هستهٔ docProps برای تکرارپذیری کامل هش
            if name == "docProps/core.xml":
                content = re.sub(
                    rb"<dcterms:(created|modified)[^>]*>.*?</dcterms:\1>",
                    rb"",
                    content,
                )
            info = zipfile.ZipInfo(filename=name, date_time=fixed_dt)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zout.writestr(info, content)

    return dst_buf.getvalue()


def build_executive_excel_workbook(
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    benefactor_id: str | None = None,
    campaign_id: str | None = None,
    include_raw_phones: bool = False,
    exported_by_label: str = "system",
    generated_at: datetime | None = None,
) -> tuple[bytes, str, dict[str, int]]:
    """تولید کامل کتابچهٔ ۸ کاربرگهٔ اکسل مدیریتی و بازگرداندن ``(bytes, sha256_hex, row_counts)``."""
    gen_ts = generated_at or timezone.now()
    gen_jalali = format_jalali_datetime(gen_ts) or ""

    # واکشی مجموعه داده‌ها بر اساس فیلترهای درخواستی
    campaigns_qs = Campaign.objects.select_related("benefactor", "category").order_by("-created_at")
    benefactors_qs = Benefactor.objects.order_by("display_order", "-total_raised_rial")
    jars_qs = CharityJar.objects.select_related("benefactor").order_by("-total_raised_rial")
    payments_qs = Payment.objects.select_related(
        "contribution",
        "contribution__user",
        "contribution__campaign",
        "contribution__charity_jar",
        "contribution__benefactor",
    ).order_by("-created_at")
    contribs_qs = Contribution.objects.select_related(
        "user",
        "campaign",
        "charity_jar",
        "benefactor",
        "ambassador_link",
        "receipt",
        "dedication_card",
    ).order_by("-created_at")
    externals_qs = ExternalContribution.objects.select_related(
        "campaign", "campaign__benefactor", "recorded_by"
    ).order_by("-created_at")
    disbursements_qs = DisbursementRequest.objects.select_related(
        "benefactor", "campaign", "requested_by", "reviewed_by"
    ).order_by("-created_at")
    recon_items_qs = (
        ReconciliationItem.objects.select_related("batch")
        .exclude(status=ReconciliationItemStatus.MATCHED)
        .order_by("-created_at")
    )

    if benefactor_id:
        campaigns_qs = campaigns_qs.filter(benefactor_id=benefactor_id)
        benefactors_qs = benefactors_qs.filter(pk=benefactor_id)
        jars_qs = jars_qs.filter(benefactor_id=benefactor_id)
        payments_qs = payments_qs.filter(contribution__benefactor_id=benefactor_id)
        contribs_qs = contribs_qs.filter(benefactor_id=benefactor_id)
        externals_qs = externals_qs.filter(campaign__benefactor_id=benefactor_id)
        disbursements_qs = disbursements_qs.filter(benefactor_id=benefactor_id)

    if campaign_id:
        campaigns_qs = campaigns_qs.filter(pk=campaign_id)
        payments_qs = payments_qs.filter(contribution__campaign_id=campaign_id)
        contribs_qs = contribs_qs.filter(campaign_id=campaign_id)
        externals_qs = externals_qs.filter(campaign_id=campaign_id)
        disbursements_qs = disbursements_qs.filter(campaign_id=campaign_id)

    if date_from:
        payments_qs = payments_qs.filter(created_at__gte=date_from)
        contribs_qs = contribs_qs.filter(created_at__gte=date_from)
        externals_qs = externals_qs.filter(created_at__gte=date_from)
        disbursements_qs = disbursements_qs.filter(created_at__gte=date_from)
    if date_to:
        payments_qs = payments_qs.filter(created_at__lte=date_to)
        contribs_qs = contribs_qs.filter(created_at__lte=date_to)
        externals_qs = externals_qs.filter(created_at__lte=date_to)
        disbursements_qs = disbursements_qs.filter(created_at__lte=date_to)

    campaigns = list(campaigns_qs)
    benefactors = list(benefactors_qs)
    jars = list(jars_qs)
    payments = list(payments_qs[:5000])
    contribs = list(contribs_qs[:5000])
    externals = list(externals_qs[:2000])
    disbursements = list(disbursements_qs[:2000])
    recon_discrepancies = list(recon_items_qs[:2000])
    ledger_accounts = list(LedgerAccount.objects.order_by("code"))

    wb = Workbook()

    # ── کاربرگ ۱: خلاصه مدیریتی + نمودار میله‌ای پیشرفت و جذب ─────────────────
    ws1 = wb.active
    assert ws1 is not None
    ws1.title = "خلاصه مدیریتی"
    _configure_rtl_print_sheet(
        ws1,
        title_banner=f"گزارش جامع مدیریتی و مالی سامانه کرادفاندینگ خیرخواهانه — تاریخ تولید: {gen_jalali}",
        col_widths=[34, 24, 24, 28],
    )

    paid_contribs = [c for c in contribs if c.status == ContributionStatus.PAID]
    total_online_rial = sum(int(c.amount_rial) for c in paid_contribs)
    total_matched_rial = sum(int(c.matched_amount_rial) for c in paid_contribs)
    total_external_rial = sum(int(e.amount_rial) for e in externals)
    total_disbursed_rial = sum(int(b.total_disbursed_rial) for b in benefactors)

    ledger_agg = LedgerPosting.objects.aggregate(dr=Sum("debit_rial"), cr=Sum("credit_rial"))
    total_dr = int(ledger_agg["dr"] or 0)
    total_cr = int(ledger_agg["cr"] or 0)
    trial_status = "تراز کامل (مورد تأیید)" if total_dr == total_cr else "هشدار عدم تراز!"

    _write_table_headers(
        ws1,
        header_row=3,
        headers=["شاخص کلیدی عملکرد (KPI)", "مقدار ریالی / عددی", "معادل تومانی", "توضیح"],
    )
    kpis: list[tuple[str, Any, Any, str]] = [
        ("تعداد کل خیریه‌ها و نهادها", len(benefactors), "-", "نهادهای تعریف‌شده در گزارش"),
        ("تعداد حرکت‌های سهم‌محور", len(campaigns), "-", "تمام وضعیت‌ها در بازه انتخابی"),
        ("تعداد قلک‌های عام خیریه", len(jars), "-", "مشارکت‌های آزاد خارج از سهم"),
        (
            "جمع مشارکت‌های آنلاین قطعی",
            total_online_rial,
            rial_to_toman(total_online_rial),
            "وصول‌شده از درگاه پرداخت",
        ),
        (
            "جمع تعهدات اعمال‌شده حامیان مضاعف",
            total_matched_rial,
            rial_to_toman(total_matched_rial),
            "سهم‌های دوبرابرشده توسط حامیان",
        ),
        (
            "جمع مشارکت‌های خارج از درگاه (آفلاین)",
            total_external_rial,
            rial_to_toman(total_external_rial),
            "ثبت‌شده در حساب انتظامی مجزا",
        ),
        (
            "جمع کل تسویه‌شده با شبای خیریه‌ها",
            total_disbursed_rial,
            rial_to_toman(total_disbursed_rial),
            "پرداخت‌های پایا/ساتنا تاییدشده",
        ),
        ("گردش تراز آزمایشی دفترکل دوطرفه", total_dr, rial_to_toman(total_dr), trial_status),
    ]
    for idx, (k_title, k_val, k_toman, k_desc) in enumerate(kpis, start=4):
        _write_data_row(
            ws1,
            row_idx=idx,
            values=[k_title, k_val, k_toman, k_desc],
            money_cols={2, 3},
        )

    # جدول کوچک برای تغذیهٔ نمودار اجرایی حرکت‌های برتر در کاربرگ اول
    chart_start_row = 14
    _write_table_headers(
        ws1,
        header_row=chart_start_row,
        headers=[
            "عنوان حرکت (نمودار جذب)",
            "مبلغ هدف (تومان)",
            "مبلغ تأمین‌شده (تومان)",
            "درصد پیشرفت",
        ],
    )
    top_campaigns = campaigns[:8]
    for offset, camp in enumerate(top_campaigns, start=1):
        _write_data_row(
            ws1,
            row_idx=chart_start_row + offset,
            values=[
                camp.title[:35],
                rial_to_toman(camp.target_amount_rial),
                rial_to_toman(camp.total_funded_rial),
                camp.progress_percent,
            ],
            money_cols={2, 3},
        )

    if top_campaigns:
        chart = BarChart()
        chart.type = "col"
        chart.style = 10
        chart.title = "مقایسه هدف و جذب منابع حرکت‌ها (تومان)"
        chart.y_axis.title = "مبلغ (تومان)"
        chart.x_axis.title = "حرکت خیرخواهانه"
        data_ref = Reference(
            ws1,
            min_col=2,
            max_col=3,
            min_row=chart_start_row,
            max_row=chart_start_row + len(top_campaigns),
        )
        cats_ref = Reference(
            ws1,
            min_col=1,
            min_row=chart_start_row + 1,
            max_row=chart_start_row + len(top_campaigns),
        )
        chart.add_data(data_ref, titles_from_data=True)
        chart.set_categories(cats_ref)
        chart.width = 18
        chart.height = 10
        ws1.add_chart(chart, "F3")

    # ── کاربرگ ۲: وضعیت تفصیلی حرکت‌های سهم‌محور ─────────────────────────────
    ws2 = wb.create_sheet(title="حرکت‌ها")
    _configure_rtl_print_sheet(
        ws2,
        title_banner="گزارش تفصیلی حرکت‌های خیرخواهانهٔ سهم‌محور و شمارنده‌های سهم",
        col_widths=[30, 12, 22, 16, 14, 16, 12, 12, 12, 12, 12, 12, 18, 18, 18, 20],
    )
    _write_table_headers(
        ws2,
        header_row=3,
        headers=[
            "عنوان حرکت",
            "پیوندک",
            "خیریه مجری",
            "دسته‌بندی",
            "وضعیت",
            "قیمت هر سهم (ریال)",
            "کل سهم‌ها",
            "سهم آنلاین",
            "سهم مضاعف",
            "سهم خارجی",
            "رزرو فعال",
            "سهم باقی‌مانده",
            "هدف کل (ریال)",
            "جمع تأمین‌شده (ریال)",
            "معادل تأمین‌شده (تومان)",
            "پیشرفت اجرا (%)",
        ],
    )
    for idx, camp in enumerate(campaigns, start=4):
        _write_data_row(
            ws2,
            row_idx=idx,
            values=[
                camp.title,
                camp.short_code,
                camp.benefactor.name,
                camp.category.title if camp.category else "-",
                camp.status,
                camp.share_price_rial,
                camp.total_shares,
                camp.paid_shares,
                camp.matched_shares,
                camp.external_shares,
                camp.reserved_shares,
                camp.remaining_shares,
                camp.target_amount_rial,
                camp.total_funded_rial,
                rial_to_toman(camp.total_funded_rial),
                camp.physical_progress_percent,
            ],
            money_cols={6, 7, 8, 9, 10, 11, 12, 13, 14, 15},
        )
    ws2.auto_filter.ref = f"A3:P{max(3, 3 + len(campaigns))}"

    # ── کاربرگ ۳: خیریه‌ها و قلک‌های عام ───────────────────────────────────────
    ws3 = wb.create_sheet(title="خیریه‌ها و قلک‌ها")
    _configure_rtl_print_sheet(
        ws3,
        title_banner="کارنامهٔ مالی خیریه‌ها، شماره شبا، مانده قابل تسویه و قلک‌های عام",
        col_widths=[28, 16, 28, 14, 14, 20, 20, 20, 20],
    )
    _write_table_headers(
        ws3,
        header_row=3,
        headers=[
            "نام خیریه / نهاد",
            "استان",
            "شماره شبا (IBAN)",
            "حرکت فعال",
            "حرکت تکمیل‌شده",
            "کل جذب‌شده (ریال)",
            "کل تسویه‌شده (ریال)",
            "مانده قابل تسویه دفترکل (ریال)",
            "مانده قابل تسویه (تومان)",
        ],
    )
    for idx, ben in enumerate(benefactors, start=4):
        payable_rial = get_benefactor_payable_balance_rial(benefactor_id=ben.id)
        _write_data_row(
            ws3,
            row_idx=idx,
            values=[
                ben.name,
                ben.province or "-",
                ben.iban or "-",
                ben.active_campaigns_count,
                ben.completed_campaigns_count,
                ben.total_raised_rial,
                ben.total_disbursed_rial,
                payable_rial,
                rial_to_toman(payable_rial),
            ],
            money_cols={6, 7, 8, 9},
        )

    # ── کاربرگ ۴: تراکنش‌های درگاه پرداخت آنلاین ───────────────────────────────
    ws4 = wb.create_sheet(title="پرداخت‌های درگاه")
    _configure_rtl_print_sheet(
        ws4,
        title_banner="ریز تراکنش‌های درگاه پرداخت اینترنتی (زرین‌پال / Sandbox)",
        col_widths=[20, 20, 14, 24, 20, 14, 18, 28, 18, 18],
    )
    _write_table_headers(
        ws4,
        header_row=3,
        headers=[
            "تاریخ ایجاد (شمسی)",
            "تاریخ تأیید (شمسی)",
            "درگاه",
            "Authority",
            "شماره پیگیری شاپرک",
            "وضعیت",
            "موبایل خیر",
            "حرکت / قلک مقصد",
            "مبلغ (ریال)",
            "مبلغ (تومان)",
        ],
    )
    for idx, pay in enumerate(payments, start=4):
        c = pay.contribution
        phone_cell = c.user.phone if include_raw_phones else mask_phone(c.user.phone)
        target_name = (
            c.campaign.title
            if c.campaign
            else (c.charity_jar.title if c.charity_jar else c.benefactor.name)
        )
        _write_data_row(
            ws4,
            row_idx=idx,
            values=[
                format_jalali_datetime(pay.created_at) or "",
                format_jalali_datetime(pay.verified_at) or "-",
                pay.gateway_name,
                pay.authority,
                pay.ref_id or "-",
                pay.status,
                phone_cell,
                target_name,
                pay.amount_rial,
                rial_to_toman(pay.amount_rial),
            ],
            money_cols={9, 10},
        )

    # ── کاربرگ ۵: مشارکت‌ها، نیت‌نامه‌ها و سفیران ─────────────────────────────
    ws5 = wb.create_sheet(title="مشارکت‌ها و نیت‌نامه‌ها")
    _configure_rtl_print_sheet(
        ws5,
        title_banner="ریز مشارکت‌های سهم‌محور و قلک عام به همراه رسید، سفیر معرف و نیت‌نامه",
        col_widths=[20, 20, 16, 26, 20, 12, 12, 18, 18, 16, 24],
    )
    _write_table_headers(
        ws5,
        header_row=3,
        headers=[
            "زمان پرداخت (شمسی)",
            "شماره رسید",
            "نوع مقصد",
            "عنوان حرکت / قلک",
            "نام نمایشی خیر",
            "تعداد سهم",
            "سهم مضاعف",
            "مبلغ (ریال)",
            "مبلغ (تومان)",
            "کد سفیر معرف",
            "نیت‌نامه (به نام/یاد)",
        ],
    )
    for idx, c in enumerate(contribs, start=4):
        receipt_obj = getattr(c, "receipt", None)
        ded_obj = getattr(c, "dedication_card", None)
        donor_label = (
            "خیر گمنام" if c.is_anonymous else (c.user.display_name or mask_phone(c.user.phone))
        )
        target_name = (
            c.campaign.title
            if c.campaign
            else (c.charity_jar.title if c.charity_jar else c.benefactor.name)
        )
        _write_data_row(
            ws5,
            row_idx=idx,
            values=[
                format_jalali_datetime(c.paid_at or c.created_at) or "",
                receipt_obj.receipt_number if receipt_obj else "-",
                c.target_kind,
                target_name,
                donor_label,
                c.shares_count,
                c.matched_shares_awarded,
                c.amount_rial,
                rial_to_toman(c.amount_rial),
                c.ambassador_link.code if c.ambassador_link else "-",
                ded_obj.honoree_name if ded_obj else "-",
            ],
            money_cols={6, 7, 8, 9},
        )

    # ── کاربرگ ۶: مشارکت‌های خارج از درگاه (آفلاین) ───────────────────────────
    ws6 = wb.create_sheet(title="مشارکت‌های خارجی")
    _configure_rtl_print_sheet(
        ws6,
        title_banner="مشارکت‌های مستقیم خارج از درگاه آنلاین (حساب انتظامی مجزا)",
        col_widths=[20, 28, 22, 22, 18, 12, 18, 18, 28],
    )
    _write_table_headers(
        ws6,
        header_row=3,
        headers=[
            "تاریخ ثبت (شمسی)",
            "عنوان حرکت",
            "خیریه",
            "نام بانی / حامی مستقیم",
            "شماره سند مرجع",
            "تعداد سهم",
            "مبلغ معادل (ریال)",
            "مبلغ معادل (تومان)",
            "توضیحات",
        ],
    )
    for idx, ext in enumerate(externals, start=4):
        _write_data_row(
            ws6,
            row_idx=idx,
            values=[
                format_jalali_datetime(ext.created_at) or "",
                ext.campaign.title,
                ext.campaign.benefactor.name,
                ext.donor_display_name,
                ext.reference_code,
                ext.shares_count,
                ext.amount_rial,
                rial_to_toman(ext.amount_rial),
                ext.note or "-",
            ],
            money_cols={6, 7, 8},
        )

    # ── کاربرگ ۷: تسویه‌های خیریه و تراز آزمایشی دفترکل دوطرفه ────────────────
    ws7 = wb.create_sheet(title="تسویه‌ها و دفترکل")
    _configure_rtl_print_sheet(
        ws7,
        title_banner="درخواست‌های تسویهٔ چهارچشمی با خیریه‌ها و تراز آزمایشی دفترکل",
        col_widths=[20, 24, 28, 16, 20, 18, 18, 24],
    )
    _write_table_headers(
        ws7,
        header_row=3,
        headers=[
            "تاریخ ثبت (شمسی)",
            "خیریه ذی‌نفع",
            "شماره شبای مقصد",
            "وضعیت",
            "شماره پیگیری پایا/ساتنا",
            "مبلغ (ریال)",
            "مبلغ (تومان)",
            "توضیح بررسی",
        ],
    )
    cur_r = 4
    for disb in disbursements:
        _write_data_row(
            ws7,
            row_idx=cur_r,
            values=[
                format_jalali_datetime(disb.created_at) or "",
                disb.benefactor.name,
                disb.destination_iban,
                disb.status,
                disb.bank_reference_number or "-",
                disb.amount_rial,
                rial_to_toman(disb.amount_rial),
                disb.review_reason or disb.request_note or "-",
            ],
            money_cols={6, 7},
        )
        cur_r += 1

    cur_r += 2
    _write_table_headers(
        ws7,
        header_row=cur_r,
        headers=[
            "کد سرفصل دفترکل",
            "عنوان حساب",
            "ماهیت حساب",
            "-",
            "-",
            "گردش بدهکار (ریال)",
            "گردش بستانکار (ریال)",
            "مانده نهایی (ریال)",
        ],
    )
    for acc in ledger_accounts:
        cur_r += 1
        _write_data_row(
            ws7,
            row_idx=cur_r,
            values=[
                acc.code,
                acc.title,
                acc.account_type,
                "-",
                "-",
                acc.debit_total_rial,
                acc.credit_total_rial,
                acc.balance_rial,
            ],
            money_cols={6, 7, 8},
        )

    # ── کاربرگ ۸: مغایرت‌گیری درگاه و شناسنامه اصالت سند ──────────────────────
    ws8 = wb.create_sheet(title="مغایرت‌گیری و اصالت")
    _configure_rtl_print_sheet(
        ws8,
        title_banner="مغایرت‌های صورت‌حساب درگاه پرداخت و شناسنامهٔ رمزنگاری سند",
        col_widths=[16, 24, 20, 18, 18, 22, 34],
    )
    _write_table_headers(
        ws8,
        header_row=3,
        headers=[
            "درگاه",
            "Authority",
            "شماره پیگیری",
            "مبلغ درگاه (ریال)",
            "مبلغ داخلی (ریال)",
            "نوع مغایرت",
            "شرح",
        ],
    )
    r8 = 4
    for item in recon_discrepancies:
        _write_data_row(
            ws8,
            row_idx=r8,
            values=[
                item.batch.gateway_name,
                item.authority,
                item.ref_id or "-",
                item.gateway_amount_rial,
                item.internal_amount_rial,
                item.status,
                item.note,
            ],
            money_cols={4, 5},
            highlight_alert=True,
        )
        r8 += 1

    r8 += 2
    _write_table_headers(
        ws8,
        header_row=r8,
        headers=["مشخصهٔ اصالت سند", "مقدار ثبت‌شده", "-", "-", "-", "-", "-"],
    )
    provenance_rows = [
        ("صادرکنندهٔ گزارش", exported_by_label),
        ("زمان تولید (شمسی)", gen_jalali),
        (
            "سطح نمایش شماره موبایل خیرین",
            "کامل (Step-Up MFA)" if include_raw_phones else "پوشانده‌شده (پیش‌فرض امن)",
        ),
        ("وضعیت تراز آزمایشی دفترکل", trial_status),
    ]
    for p_key, p_val in provenance_rows:
        r8 += 1
        _write_data_row(ws8, row_idx=r8, values=[p_key, p_val, "-", "-", "-", "-", "-"])

    raw_buf = io.BytesIO()
    wb.save(raw_buf)
    canonical_bytes = _canonicalize_xlsx_bytes(raw_buf.getvalue())
    sha256_hex = hashlib.sha256(canonical_bytes).hexdigest()

    row_counts = {
        "campaigns": len(campaigns),
        "benefactors": len(benefactors),
        "payments": len(payments),
        "contributions": len(contribs),
        "external_contributions": len(externals),
        "disbursements": len(disbursements),
        "reconciliation_discrepancies": len(recon_discrepancies),
    }
    return canonical_bytes, sha256_hex, row_counts
