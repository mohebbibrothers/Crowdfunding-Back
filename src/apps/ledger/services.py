"""سرویس‌های هستهٔ حسابداری دوطرفه، تسویهٔ چهارچشمی با خیریه، مغایرت‌گیری و کنترل تراز."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from apps.audit.choices import AuditAction
from apps.audit.services import record_audit_event
from apps.benefactors.models import Benefactor, CharityJar
from apps.campaigns.models import Campaign
from apps.core.cache import bump_epoch
from apps.core.errors import ConflictError, NotFoundError, ValidationError as DomainValidationError
from apps.core.policy import get_policy
from apps.identity.models import User
from apps.identity.validators import validate_iranian_iban
from apps.ledger.choices import (
    DisbursementStatus,
    JournalEntryKind,
    LedgerAccountType,
    ReconciliationItemStatus,
)
from apps.ledger.models import (
    DisbursementRequest,
    FinancialControlSnapshot,
    JournalEntry,
    LedgerAccount,
    LedgerPosting,
    ReconciliationBatch,
    ReconciliationItem,
)

# کدهای ثابت حساب‌های سیستمی دفترکل
ACC_GATEWAY_RECEIVABLE = "SYS:ASSET:GATEWAY_RECEIVABLE"
ACC_MATCHING_POOL = "SYS:ASSET:MATCHING_SPONSOR_POOL"
ACC_EXTERNAL_CUSTODY = "SYS:ASSET:EXTERNAL_CUSTODY"
ACC_SETTLEMENT_BANK = "SYS:ASSET:SETTLEMENT_BANK"


@dataclass(frozen=True, slots=True)
class PostingLineSpec:
    """مشخصات یک ردیف بدهکار یا بستانکار برای ثبت سند روزنامه."""

    account_code: str
    account_title: str
    account_type: str
    debit_rial: int = 0
    credit_rial: int = 0
    benefactor_id: Any = None
    memo: str = ""


def benefactor_online_payable_spec(benefactor: Benefactor) -> tuple[str, str, str]:
    """کد و مشخصات حساب بدهی قابل تسویهٔ آنلاین به یک خیریه مشخص."""
    return (
        f"BEN:LIAB:ONLINE_PAYABLE:{benefactor.id}",
        f"بدهی قابل تسویه به خیریه {benefactor.name}",
        LedgerAccountType.LIABILITY,
    )


def benefactor_external_equity_spec(benefactor: Benefactor) -> tuple[str, str, str]:
    """کد و مشخصات حساب منابع مستقیم/آفلاین شناسایی‌شده نزد خیریه."""
    return (
        f"BEN:EQUITY:EXTERNAL_DIRECT:{benefactor.id}",
        f"منابع مستقیم خارج از درگاه خیریه {benefactor.name}",
        LedgerAccountType.EQUITY,
    )


def _ensure_locked_accounts(specs: list[PostingLineSpec]) -> dict[str, LedgerAccount]:
    """ایجاد (در صورت نبود) و قفل کردن حساب‌های دفترکل به ترتیب الفبایی کد برای پیشگیری از Deadlock."""
    unique_by_code = {s.account_code: s for s in specs}
    sorted_codes = sorted(unique_by_code.keys())

    for code in sorted_codes:
        spec = unique_by_code[code]
        LedgerAccount.objects.get_or_create(
            code=code,
            defaults={
                "title": spec.account_title,
                "account_type": spec.account_type,
                "benefactor_id": spec.benefactor_id,
            },
        )

    locked = list(
        LedgerAccount.objects.select_for_update().filter(code__in=sorted_codes).order_by("code")
    )
    return {acc.code: acc for acc in locked}


@transaction.atomic
def post_journal_entry(
    *,
    reference_key: str,
    kind: str,
    description: str,
    lines: list[PostingLineSpec],
    campaign_id: Any = None,
    benefactor_id: Any = None,
    actor: User | None = None,
    metadata: dict[str, Any] | None = None,
) -> JournalEntry:
    """ثبت اتمیک و تکرارناپذیر یک سند حسابداری دوطرفه با راستی‌آزمایی قطعی تراز بدهکار و بستانکار."""
    existing = JournalEntry.objects.filter(reference_key=reference_key).first()
    if existing is not None:
        return existing

    if len(lines) < 2:
        raise DomainValidationError("سند حسابداری دوطرفه باید حداقل دارای دو آرتیکل باشد.")

    total_dr = 0
    total_cr = 0
    for ln in lines:
        if (ln.debit_rial > 0 and ln.credit_rial > 0) or (
            ln.debit_rial <= 0 and ln.credit_rial <= 0
        ):
            raise DomainValidationError(
                "هر آرتیکل باید دقیقاً بدهکار یا بستانکار با مبلغ مثبت باشد."
            )
        total_dr += int(ln.debit_rial)
        total_cr += int(ln.credit_rial)

    if total_dr != total_cr or total_dr <= 0:
        raise DomainValidationError(
            f"عدم تراز در سند حسابداری ({total_dr} بدهکار != {total_cr} بستانکار)."
        )

    accounts = _ensure_locked_accounts(lines)
    entry = JournalEntry.objects.create(
        reference_key=reference_key,
        kind=kind,
        description=description[:320],
        total_amount_rial=total_dr,
        campaign_id=campaign_id,
        benefactor_id=benefactor_id,
        created_by=actor,
        metadata=metadata or {},
    )

    postings: list[LedgerPosting] = []
    for ln in lines:
        acc = accounts[ln.account_code]
        postings.append(
            LedgerPosting(
                journal_entry=entry,
                account=acc,
                debit_rial=int(ln.debit_rial),
                credit_rial=int(ln.credit_rial),
                memo=ln.memo[:240],
            )
        )
        LedgerAccount.objects.filter(pk=acc.pk).update(
            debit_total_rial=F("debit_total_rial") + int(ln.debit_rial),
            credit_total_rial=F("credit_total_rial") + int(ln.credit_rial),
        )
    LedgerPosting.objects.bulk_create(postings)
    return entry


def get_benefactor_payable_balance_rial(*, benefactor_id: Any) -> int:
    """محاسبهٔ ماندهٔ قابل تسویه به خیریه از روی حساب بدهی آنلاین در دفترکل."""
    code = f"BEN:LIAB:ONLINE_PAYABLE:{benefactor_id}"
    acc = LedgerAccount.objects.filter(code=code).first()
    return acc.balance_rial if acc is not None else 0


@transaction.atomic
def create_disbursement_request(
    *,
    actor: User,
    benefactor_id: str,
    amount_rial: int,
    campaign_id: str | None = None,
    request_note: str = "",
    request: Any = None,
) -> DisbursementRequest:
    """ثبت درخواست تسویه وجه با خیریه (گام اول چرخهٔ چهارچشمی Maker)."""
    benefactor = Benefactor.objects.select_for_update().filter(pk=benefactor_id).first()
    if benefactor is None:
        raise NotFoundError("خیریهٔ مورد نظر یافت نشد.")
    if not benefactor.iban:
        raise DomainValidationError("برای خیریهٔ انتخاب‌شده شماره شبای معتبر ثبت نشده است.")
    destination_iban = validate_iranian_iban(benefactor.iban)

    if amount_rial <= 0:
        raise DomainValidationError("مبلغ درخواست تسویه باید بزرگ‌تر از صفر ریال باشد.")

    pending_sum = int(
        DisbursementRequest.objects.filter(
            benefactor=benefactor, status=DisbursementStatus.PENDING_APPROVAL
        ).aggregate(s=Sum("amount_rial"))["s"]
        or 0
    )
    available_payable = (
        get_benefactor_payable_balance_rial(benefactor_id=benefactor.id) - pending_sum
    )
    if amount_rial > available_payable:
        raise ConflictError(
            f"مبلغ درخواستی ({amount_rial:,} ریال) بیش از ماندهٔ قابل تسویهٔ آزاد خیریه ({max(0, available_payable):,} ریال) است."
        )

    campaign = None
    if campaign_id:
        campaign = (
            Campaign.objects.select_for_update()
            .filter(pk=campaign_id, benefactor=benefactor)
            .first()
        )
        if campaign is None:
            raise NotFoundError("حرکت انتخاب‌شده متعلق به این خیریه نیست یا یافت نشد.")
        camp_net_online = int(
            campaign.collected_online_rial
            + campaign.matched_amount_rial
            - campaign.disbursed_amount_rial
        )
        if amount_rial > camp_net_online:
            raise ConflictError("مبلغ تسویه از ماندهٔ تسویه‌نشدهٔ این حرکت بیشتر است.")

    disb = DisbursementRequest.objects.create(
        benefactor=benefactor,
        campaign=campaign,
        amount_rial=amount_rial,
        destination_iban=destination_iban,
        status=DisbursementStatus.PENDING_APPROVAL,
        requested_by=actor,
        request_note=request_note.strip()[:400],
    )
    record_audit_event(
        action=AuditAction.DISBURSEMENT_REQUESTED,
        actor=actor,
        target_type="DisbursementRequest",
        target_id=str(disb.id),
        metadata={
            "benefactor_id": str(benefactor.id),
            "campaign_id": str(campaign.id) if campaign else None,
            "amount_rial": amount_rial,
            "destination_iban": destination_iban,
        },
        request=request,
    )
    return disb


@transaction.atomic
def approve_or_reject_disbursement(
    *,
    actor: User,
    disbursement_id: str,
    approve: bool,
    reason: str,
    bank_reference_number: str = "",
    request: Any = None,
) -> DisbursementRequest:
    """تأیید و ثبت سند پرداخت تسویه به خیریه یا رد آن توسط مدیر دوم (Checker + Step-Up MFA)."""
    disb = (
        DisbursementRequest.objects.select_for_update()
        .select_related("benefactor", "campaign")
        .filter(pk=disbursement_id)
        .first()
    )
    if disb is None:
        raise NotFoundError("درخواست تسویه یافت نشد.")
    if disb.status != DisbursementStatus.PENDING_APPROVAL:
        raise ConflictError("این درخواست تسویه پیش‌تر تعیین تکلیف شده است.")

    require_maker_checker = bool(get_policy("governance.maker_checker_disbursement"))
    if require_maker_checker and disb.requested_by_id == actor.id:
        raise ConflictError(
            "کنترل چهارچشمی (Maker-Checker): ثبت‌کنندهٔ درخواست تسویه نمی‌تواند تأییدکنندهٔ نهایی همان درخواست باشد."
        )

    now = timezone.now()
    if not approve:
        disb.status = DisbursementStatus.REJECTED
        disb.reviewed_by = actor
        disb.reviewed_at = now
        disb.review_reason = reason.strip()[:400]
        disb.save(
            update_fields=["status", "reviewed_by", "reviewed_at", "review_reason", "updated_at"]
        )
        record_audit_event(
            action=AuditAction.DISBURSEMENT_REJECTED,
            actor=actor,
            target_type="DisbursementRequest",
            target_id=str(disb.id),
            reason=reason,
            metadata={"amount_rial": disb.amount_rial},
            request=request,
        )
        return disb

    if not bank_reference_number.strip():
        raise DomainValidationError(
            "ثبت شماره پیگیری بانکی (پایا/ساتنا) هنگام تأیید نهایی تسویه الزامی است."
        )

    payable_balance = get_benefactor_payable_balance_rial(benefactor_id=disb.benefactor_id)
    if disb.amount_rial > payable_balance:
        raise ConflictError("ماندهٔ حساب بدهی خیریه برای انجام این تسویه کافی نیست.")

    ben_code, ben_title, ben_type = benefactor_online_payable_spec(disb.benefactor)
    entry = post_journal_entry(
        reference_key=f"disbursement:{disb.id}",
        kind=JournalEntryKind.DISBURSEMENT_PAID,
        description=f"تسویه پایا/ساتنا به شبای {disb.destination_iban} ({disb.benefactor.name})",
        benefactor_id=disb.benefactor_id,
        campaign_id=disb.campaign_id,
        actor=actor,
        metadata={"bank_reference_number": bank_reference_number.strip()},
        lines=[
            PostingLineSpec(
                account_code=ben_code,
                account_title=ben_title,
                account_type=ben_type,
                debit_rial=disb.amount_rial,
                benefactor_id=disb.benefactor_id,
                memo=f"تسویه شبا پیگیری {bank_reference_number.strip()}",
            ),
            PostingLineSpec(
                account_code=ACC_SETTLEMENT_BANK,
                account_title="حساب بانکی تسویه پلتفرم",
                account_type=LedgerAccountType.ASSET,
                credit_rial=disb.amount_rial,
                memo=f"پرداخت به خیریه {disb.benefactor.name}",
            ),
        ],
    )

    Benefactor.objects.filter(pk=disb.benefactor_id).update(
        total_disbursed_rial=F("total_disbursed_rial") + disb.amount_rial
    )
    if disb.campaign_id is not None:
        Campaign.objects.filter(pk=disb.campaign_id).update(
            disbursed_amount_rial=F("disbursed_amount_rial") + disb.amount_rial
        )

    disb.status = DisbursementStatus.APPROVED_PAID
    disb.reviewed_by = actor
    disb.reviewed_at = now
    disb.review_reason = reason.strip()[:400]
    disb.bank_reference_number = bank_reference_number.strip()[:80]
    disb.journal_entry = entry
    disb.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "review_reason",
            "bank_reference_number",
            "journal_entry",
            "updated_at",
        ]
    )

    record_audit_event(
        action=AuditAction.DISBURSEMENT_APPROVED,
        actor=actor,
        target_type="DisbursementRequest",
        target_id=str(disb.id),
        reason=reason,
        metadata={
            "amount_rial": disb.amount_rial,
            "destination_iban": disb.destination_iban,
            "bank_reference_number": disb.bank_reference_number,
            "journal_entry_id": str(entry.id),
        },
        request=request,
    )
    transaction.on_commit(lambda: bump_epoch("campaigns"))
    transaction.on_commit(lambda: bump_epoch("benefactors"))
    return disb


@dataclass(frozen=True, slots=True)
class VerifiedPaymentRecord:
    """نمایهٔ تراکنش تأییدشدهٔ درگاه جهت مغایرت‌گیری مستقل از مدل‌های اپ بالاتر (Hexagonal Port)."""

    authority: str
    ref_id: str
    amount_rial: int


_VERIFIED_PAYMENT_PROVIDER: Callable[[str, Any, Any], list[VerifiedPaymentRecord]] | None = None


def register_verified_payment_provider(
    provider: Callable[[str, Any, Any], list[VerifiedPaymentRecord]],
) -> None:
    """ثبت تأمین‌کنندهٔ تراکنش‌های تأییدشدهٔ داخلی توسط اپ مشارکت‌ها."""
    global _VERIFIED_PAYMENT_PROVIDER  # noqa: PLW0603
    _VERIFIED_PAYMENT_PROVIDER = provider


@transaction.atomic
def run_gateway_reconciliation(
    *,
    actor: User,
    gateway_name: str,
    period_start: Any,
    period_end: Any,
    settlement_rows: list[dict[str, Any]],
    request: Any = None,
) -> ReconciliationBatch:
    """مغایرت‌گیری خودکار ردیف‌های تسویهٔ درگاه با پرداخت‌های موفق داخلی در بازهٔ زمانی مشخص."""
    records = (
        _VERIFIED_PAYMENT_PROVIDER(gateway_name, period_start, period_end)
        if _VERIFIED_PAYMENT_PROVIDER is not None
        else []
    )
    internal_payments = {p.authority: p for p in records}

    seen_authorities: set[str] = set()
    items_to_create: list[ReconciliationItem] = []
    matched_count = 0
    discrepancy_count = 0
    gateway_total = 0
    internal_total = sum(int(p.amount_rial) for p in internal_payments.values())

    batch = ReconciliationBatch.objects.create(
        gateway_name=gateway_name,
        period_start=period_start,
        period_end=period_end,
        gateway_reported_count=len(settlement_rows),
        internal_total_rial=internal_total,
        created_by=actor,
    )

    for row in settlement_rows:
        auth = str(row["authority"]).strip()
        gw_amount = int(row["amount_rial"])
        ref_id = str(row.get("ref_id") or "").strip()
        gateway_total += gw_amount
        seen_authorities.add(auth)

        internal_p = internal_payments.get(auth)
        if internal_p is None:
            discrepancy_count += 1
            items_to_create.append(
                ReconciliationItem(
                    batch=batch,
                    authority=auth,
                    ref_id=ref_id,
                    gateway_amount_rial=gw_amount,
                    internal_amount_rial=0,
                    status=ReconciliationItemStatus.MISSING_INTERNAL,
                    note="تراکنش در فایل تسویه درگاه وجود دارد اما در سامانه تایید نشده است.",
                )
            )
        elif int(internal_p.amount_rial) != gw_amount:
            discrepancy_count += 1
            items_to_create.append(
                ReconciliationItem(
                    batch=batch,
                    authority=auth,
                    ref_id=ref_id or internal_p.ref_id,
                    gateway_amount_rial=gw_amount,
                    internal_amount_rial=int(internal_p.amount_rial),
                    status=ReconciliationItemStatus.AMOUNT_MISMATCH,
                    note="مبلغ فایل تسویه درگاه با مبلغ ثبت‌شدهٔ داخلی یکسان نیست.",
                )
            )
        else:
            matched_count += 1
            items_to_create.append(
                ReconciliationItem(
                    batch=batch,
                    authority=auth,
                    ref_id=ref_id or internal_p.ref_id,
                    gateway_amount_rial=gw_amount,
                    internal_amount_rial=int(internal_p.amount_rial),
                    status=ReconciliationItemStatus.MATCHED,
                    note="تطبیق کامل ریالی و مرجع.",
                )
            )

    for auth, internal_p in internal_payments.items():
        if auth not in seen_authorities:
            discrepancy_count += 1
            items_to_create.append(
                ReconciliationItem(
                    batch=batch,
                    authority=auth,
                    ref_id=internal_p.ref_id,
                    gateway_amount_rial=0,
                    internal_amount_rial=int(internal_p.amount_rial),
                    status=ReconciliationItemStatus.MISSING_GATEWAY,
                    note="تراکنش در سامانه تایید شده اما در فایل تسویه درگاه یافت نشد.",
                )
            )

    ReconciliationItem.objects.bulk_create(items_to_create)
    batch.matched_count = matched_count
    batch.discrepancy_count = discrepancy_count
    batch.gateway_total_rial = gateway_total
    batch.save(
        update_fields=[
            "matched_count",
            "discrepancy_count",
            "gateway_total_rial",
            "updated_at",
        ]
    )

    record_audit_event(
        action=AuditAction.RECONCILIATION_IMPORTED,
        actor=actor,
        target_type="ReconciliationBatch",
        target_id=str(batch.id),
        metadata={
            "gateway_name": gateway_name,
            "matched_count": matched_count,
            "discrepancy_count": discrepancy_count,
            "gateway_total_rial": gateway_total,
            "internal_total_rial": internal_total,
        },
        request=request,
    )
    return batch


@transaction.atomic
def capture_financial_control_snapshot(
    *,
    actor: User | None = None,
) -> FinancialControlSnapshot:
    """محاسبهٔ تراز آزمایشی کل دفترکل و راستی‌آزمایی انطباق صفر ریالی با شمارنده‌های حرکت‌ها و قلک‌ها."""
    agg = LedgerPosting.objects.aggregate(
        dr=Sum("debit_rial"),
        cr=Sum("credit_rial"),
    )
    total_dr = int(agg["dr"] or 0)
    total_cr = int(agg["cr"] or 0)

    gw_acc = LedgerAccount.objects.filter(code=ACC_GATEWAY_RECEIVABLE).first()
    ext_acc = LedgerAccount.objects.filter(code=ACC_EXTERNAL_CUSTODY).first()

    payable_accounts = LedgerAccount.objects.filter(code__startswith="BEN:LIAB:ONLINE_PAYABLE:")
    total_payable = sum(acc.balance_rial for acc in payable_accounts)

    # جمع کل جذب آنلاین + مضاعف - مستردشده - تسویه‌شده در سطح مدل‌های خوانشی
    camp_agg = Campaign.objects.aggregate(
        online=Sum("collected_online_rial"),
        matched=Sum("matched_amount_rial"),
    )
    jar_agg = CharityJar.objects.aggregate(online=Sum("total_raised_rial"))
    ben_agg = Benefactor.objects.aggregate(disbursed=Sum("total_disbursed_rial"))

    expected_payable = (
        int(camp_agg["online"] or 0)
        + int(camp_agg["matched"] or 0)
        + int(jar_agg["online"] or 0)
        - int(ben_agg["disbursed"] or 0)
    )
    drift = total_payable - expected_payable

    return FinancialControlSnapshot.objects.create(
        total_debits_rial=total_dr,
        total_credits_rial=total_cr,
        gateway_receivable_rial=gw_acc.balance_rial if gw_acc else 0,
        benefactor_payable_rial=total_payable,
        external_custody_rial=ext_acc.balance_rial if ext_acc else 0,
        is_balanced=(total_dr == total_cr and drift == 0),
        counter_drift_rial=drift,
        captured_by=actor,
    )
