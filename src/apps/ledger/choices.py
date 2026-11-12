"""شمارشی‌های کدینگ حسابداری دوطرفه، اسناد مالی، تسویه با خیریه و مغایرت‌گیری درگاه."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class LedgerAccountType(models.TextChoices):
    """ماهیت حساب در معادلهٔ حسابداری."""

    ASSET = "asset", _("دارایی (ماهیت بدهکار)")
    LIABILITY = "liability", _("بدهی به خیریه/امانی (ماهیت بستانکار)")
    EQUITY = "equity", _("حساب انتظامی/شناسایی منابع")


class JournalEntryKind(models.TextChoices):
    """نوع رویداد مالی ثبت‌شده در دفتر روزنامه."""

    CONTRIBUTION_PAID = "contribution_paid", _("وصول مشارکت آنلاین از درگاه")
    MATCHING_GRANT_APPLIED = "matching_grant_applied", _("اعمال سهم حامی مضاعف‌کننده")
    EXTERNAL_CONTRIBUTION = "external_contribution", _("ثبت مشارکت خارج از درگاه (آفلاین)")
    CONTRIBUTION_REFUNDED = "contribution_refunded", _("استرداد وجه مشارکت")
    DISBURSEMENT_PAID = "disbursement_paid", _("تسویه و واریز شبا به خیریه")
    MANUAL_ADJUSTMENT = "manual_adjustment", _("سند اصلاحی مدیریتی مستند")


class DisbursementStatus(models.TextChoices):
    """وضعیت چرخهٔ چهارچشمی (Maker-Checker) درخواست تسویه با خیریه."""

    PENDING_APPROVAL = "pending_approval", _("در انتظار تأیید مدیر مالی دوم")
    APPROVED_PAID = "approved_paid", _("تأیید و به حساب شبا واریز شد")
    REJECTED = "rejected", _("ردشده")


class ReconciliationItemStatus(models.TextChoices):
    """نتیجهٔ تطبیق هر ردیف فایل شاپرک/زرین‌پال با دفتر داخلی."""

    MATCHED = "matched", _("منطبق")
    AMOUNT_MISMATCH = "amount_mismatch", _("مغایرت مبلغ ریالی")
    MISSING_INTERNAL = "missing_internal", _("موجود در درگاه / فاقد پرداخت موفق داخلی")
    MISSING_GATEWAY = "missing_gateway", _("پرداخت موفق داخلی / غایب در فایل تسویه درگاه")
