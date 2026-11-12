"""مدل‌های دفترکل حسابداری دوطرفه، درخواست تسویهٔ چهارچشمی، مغایرت‌گیری و اسنپ‌شات کنترل مالی."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.benefactors.models import Benefactor
from apps.campaigns.models import Campaign
from apps.core.models import BaseModel
from apps.ledger.choices import (
    DisbursementStatus,
    JournalEntryKind,
    LedgerAccountType,
    ReconciliationItemStatus,
)


class LedgerAccount(BaseModel):
    """سرفصل حساب در دفترکل دوطرفه (تفکیک حساب‌های درگاه، حامی مضاعف، آفلاین و بدهی هر خیریه)."""

    code = models.CharField(max_length=96, unique=True, verbose_name=_("کد یکتای سرفصل"))
    title = models.CharField(max_length=200, verbose_name=_("عنوان حساب"))
    account_type = models.CharField(
        max_length=16, choices=LedgerAccountType.choices, db_index=True, verbose_name=_("نوع حساب")
    )
    benefactor = models.ForeignKey(
        Benefactor,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ledger_accounts",
        verbose_name=_("خیریهٔ مرتبط"),
    )
    debit_total_rial = models.BigIntegerField(default=0, verbose_name=_("گردش بدهکار (ریال)"))
    credit_total_rial = models.BigIntegerField(default=0, verbose_name=_("گردش بستانکار (ریال)"))

    class Meta:
        verbose_name = _("حساب دفترکل")
        verbose_name_plural = _("حساب‌های دفترکل")
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=Q(debit_total_rial__gte=0) & Q(credit_total_rial__gte=0),
                name="ledger_account_non_negative_turnovers_chk",
            ),
        ]

    def __str__(self) -> str:
        """نمایش کد و عنوان حساب."""
        return f"{self.code} — {self.title}"

    @property
    def balance_rial(self) -> int:
        """ماندهٔ حساب بر حسب ماهیت آن (دارایی: بدهکار منهای بستانکار؛ بدهی/سرمایه: برعکس)."""
        if self.account_type == LedgerAccountType.ASSET:
            return int(self.debit_total_rial - self.credit_total_rial)
        return int(self.credit_total_rial - self.debit_total_rial)


class JournalEntry(BaseModel):
    """سند روزنامهٔ تغییرناپذیر حسابداری دوطرفه (همواره تراز: بدهکار == بستانکار)."""

    reference_key = models.CharField(
        max_length=128,
        unique=True,
        help_text=_("کلید یکتای جلوگیری از ثبت دوبارهٔ یک رویداد مالی."),
        verbose_name=_("کلید مرجع یکتا"),
    )
    kind = models.CharField(
        max_length=32, choices=JournalEntryKind.choices, db_index=True, verbose_name=_("نوع رویداد")
    )
    description = models.CharField(max_length=320, verbose_name=_("شرح سند"))
    total_amount_rial = models.BigIntegerField(verbose_name=_("جمع تراز سند (ریال)"))
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="journal_entries",
        verbose_name=_("حرکت مرتبط"),
    )
    benefactor = models.ForeignKey(
        Benefactor,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="journal_entries",
        verbose_name=_("خیریهٔ مرتبط"),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posted_journal_entries",
        verbose_name=_("کاربر ثبت‌کننده"),
    )
    metadata = models.JSONField(default=dict, blank=True, verbose_name=_("فراداده"))

    class Meta:
        verbose_name = _("سند روزنامه")
        verbose_name_plural = _("اسناد روزنامه")
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(total_amount_rial__gt=0),
                name="journal_entry_positive_total_chk",
            ),
        ]

    def __str__(self) -> str:
        """نمایش کلید مرجع و مبلغ سند."""
        return f"{self.reference_key} ({self.total_amount_rial} IRR)"


class LedgerPosting(BaseModel):
    """آرتیکل بدهکار یا بستانکار در ذیل یک سند روزنامه."""

    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name="postings",
        verbose_name=_("سند روزنامه"),
    )
    account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="postings",
        verbose_name=_("سرفصل حساب"),
    )
    debit_rial = models.BigIntegerField(default=0, verbose_name=_("بدهکار (ریال)"))
    credit_rial = models.BigIntegerField(default=0, verbose_name=_("بستانکار (ریال)"))
    memo = models.CharField(max_length=240, blank=True, default="", verbose_name=_("شرح ردیف"))

    class Meta:
        verbose_name = _("آرتیکل دفترکل")
        verbose_name_plural = _("آرتیکل‌های دفترکل")
        constraints = [
            models.CheckConstraint(
                condition=(
                    (Q(debit_rial__gt=0) & Q(credit_rial=0))
                    | (Q(credit_rial__gt=0) & Q(debit_rial=0))
                ),
                name="ledger_posting_exclusive_dr_cr_chk",
            ),
        ]

    def __str__(self) -> str:
        """نمایش حساب و مبلغ آرتیکل."""
        side = f"DR {self.debit_rial}" if self.debit_rial > 0 else f"CR {self.credit_rial}"
        return f"{self.account.code}: {side}"


class DisbursementRequest(BaseModel):
    """درخواست تسویه و پرداخت به شبای خیریه با کنترل چهارچشمی (Maker-Checker + Step-Up MFA)."""

    benefactor = models.ForeignKey(
        Benefactor,
        on_delete=models.PROTECT,
        related_name="disbursements",
        verbose_name=_("خیریهٔ ذی‌نفع"),
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="disbursements",
        verbose_name=_("حرکت مشخص (اختیاری)"),
    )
    amount_rial = models.BigIntegerField(verbose_name=_("مبلغ تسویه (ریال)"))
    destination_iban = models.CharField(
        max_length=26, verbose_name=_("شماره شبای مقصد در لحظه ثبت")
    )
    status = models.CharField(
        max_length=24,
        choices=DisbursementStatus.choices,
        default=DisbursementStatus.PENDING_APPROVAL,
        db_index=True,
        verbose_name=_("وضعیت"),
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_disbursements",
        verbose_name=_("ثبت‌کننده (Maker)"),
    )
    request_note = models.CharField(
        max_length=400, blank=True, default="", verbose_name=_("توضیح درخواست")
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_disbursements",
        verbose_name=_("تأییدکننده (Checker)"),
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("زمان بررسی"))
    review_reason = models.CharField(
        max_length=400, blank=True, default="", verbose_name=_("شرح تأیید/رد")
    )
    bank_reference_number = models.CharField(
        max_length=80, blank=True, default="", verbose_name=_("شماره پیگیری پایا/ساتنا")
    )
    journal_entry = models.OneToOneField(
        JournalEntry,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="disbursement",
        verbose_name=_("سند حسابداری تسویه"),
    )

    class Meta:
        verbose_name = _("درخواست تسویه با خیریه")
        verbose_name_plural = _("درخواست‌های تسویه با خیریه‌ها")
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_rial__gt=0),
                name="disbursement_positive_amount_chk",
            ),
        ]

    def __str__(self) -> str:
        """نمایش خیریه، مبلغ و وضعیت تسویه."""
        return f"{self.benefactor.name}: {self.amount_rial} IRR [{self.status}]"


class ReconciliationBatch(BaseModel):
    """دستهٔ مغایرت‌گیری صورت‌حساب درگاه پرداخت با دفاتر داخلی سامانه."""

    gateway_name = models.CharField(max_length=32, verbose_name=_("نام درگاه"))
    period_start = models.DateTimeField(verbose_name=_("شروع بازهٔ تسویه"))
    period_end = models.DateTimeField(verbose_name=_("پایان بازهٔ تسویه"))
    gateway_reported_count = models.PositiveIntegerField(
        default=0, verbose_name=_("تعداد در فایل درگاه")
    )
    matched_count = models.PositiveIntegerField(default=0, verbose_name=_("تعداد منطبق"))
    discrepancy_count = models.PositiveIntegerField(default=0, verbose_name=_("تعداد مغایرت"))
    gateway_total_rial = models.BigIntegerField(default=0, verbose_name=_("جمع ریالی فایل درگاه"))
    internal_total_rial = models.BigIntegerField(default=0, verbose_name=_("جمع ریالی دفتر داخلی"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reconciliation_batches",
        verbose_name=_("کاربر اجراکننده"),
    )

    class Meta:
        verbose_name = _("دستهٔ مغایرت‌گیری درگاه")
        verbose_name_plural = _("دسته‌های مغایرت‌گیری درگاه")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        """نمایش درگاه و تعداد مغایرت‌ها."""
        return f"{self.gateway_name} [discrepancies={self.discrepancy_count}]"


class ReconciliationItem(BaseModel):
    """ردیف جزئی نتیجهٔ مغایرت‌گیری یک تراکنش درگاه."""

    batch = models.ForeignKey(
        ReconciliationBatch,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("دستهٔ مغایرت‌گیری"),
    )
    authority = models.CharField(max_length=80, db_index=True, verbose_name=_("شناسهٔ Authority"))
    ref_id = models.CharField(
        max_length=80, blank=True, default="", verbose_name=_("شماره پیگیری درگاه")
    )
    gateway_amount_rial = models.BigIntegerField(
        default=0, verbose_name=_("مبلغ گزارش درگاه (ریال)")
    )
    internal_amount_rial = models.BigIntegerField(
        default=0, verbose_name=_("مبلغ ثبت داخلی (ریال)")
    )
    status = models.CharField(
        max_length=24,
        choices=ReconciliationItemStatus.choices,
        db_index=True,
        verbose_name=_("وضعیت تطبیق"),
    )
    note = models.CharField(max_length=300, blank=True, default="", verbose_name=_("توضیح مغایرت"))

    class Meta:
        verbose_name = _("ردیف مغایرت‌گیری")
        verbose_name_plural = _("ردیف‌های مغایرت‌گیری")
        ordering = ["status", "authority"]


class FinancialControlSnapshot(BaseModel):
    """اسنپ‌شات کنترلی تراز آزمایشی دفترکل و انطباق شمارنده‌های حرکت‌ها و قلک‌ها."""

    total_debits_rial = models.BigIntegerField(verbose_name=_("جمع گردش بدهکار کل (ریال)"))
    total_credits_rial = models.BigIntegerField(verbose_name=_("جمع گردش بستانکار کل (ریال)"))
    gateway_receivable_rial = models.BigIntegerField(verbose_name=_("مانده دریافتنی درگاه (ریال)"))
    benefactor_payable_rial = models.BigIntegerField(
        verbose_name=_("مانده قابل پرداخت به خیریه‌ها (ریال)")
    )
    external_custody_rial = models.BigIntegerField(
        verbose_name=_("منابع مستقیم آفلاین نزد خیریه‌ها (ریال)")
    )
    is_balanced = models.BooleanField(verbose_name=_("تراز بودن کامل دفترکل"))
    counter_drift_rial = models.BigIntegerField(
        default=0, verbose_name=_("اختلاف شمارندهٔ حرکت‌ها/قلک‌ها با دفترکل (ریال)")
    )
    captured_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="financial_snapshots",
        verbose_name=_("کاربر ثبت‌کننده"),
    )

    class Meta:
        verbose_name = _("اسنپ‌شات کنترل مالی")
        verbose_name_plural = _("اسنپ‌شات‌های کنترل مالی")
        ordering = ["-created_at"]
