"""سرویس ثبت اتمیک در زنجیرهٔ حسابرسی، راستی‌آزمایی پیوستگی هش و صدور لنگر امضاشده."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Final
from uuid import UUID

from django.db import transaction
from django.db.models import Max
from django.http import HttpRequest
from django.utils import timezone

from apps.audit.choices import AuditAction, AuditOutcome
from apps.audit.models import (
    GENESIS_HASH,
    AuditAnchor,
    AuditRecord,
    canonical_json,
    compute_record_hash,
)
from apps.core.crypto import sign_payload, verify_signature
from apps.core.db.serial import serialize_on
from apps.core.logging import redact_value
from apps.core.middleware import request_metadata
from apps.core.uuid7 import uuid7_hex

logger = logging.getLogger(__name__)

AUDIT_CHAIN_LOCK: Final[str] = "audit.chain"
ANCHOR_NAMESPACE: Final[str] = "audit.anchor"

REQUIRE_REASON_ACTIONS: frozenset[str] = frozenset(
    {
        AuditAction.POLICY_CHANGED,
        AuditAction.ROLE_CHANGED,
        AuditAction.MFA_RESET,
        AuditAction.PII_PHONE_REVEALED,
        AuditAction.CAMPAIGN_CLOSED,
        AuditAction.EXTERNAL_FUNDING_VOIDED,
        AuditAction.REFUND_APPROVED,
        AuditAction.ADJUSTMENT_APPLIED,
        AuditAction.DISBURSEMENT_APPROVED,
        AuditAction.DISBURSEMENT_REJECTED,
    }
)


@dataclass(slots=True)
class AuditEntry:
    """ساختار ورودی استاندارد برای ثبت یک رخداد در زنجیرهٔ حسابرسی."""

    action: str
    outcome: str = AuditOutcome.SUCCESS
    actor_id: UUID | None = None
    actor_label: str = ""
    target_type: str = ""
    target_id: str = ""
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    request: HttpRequest | None = None


def record_audit(entry: AuditEntry) -> AuditRecord:
    """افزودن اتمیک رکورد جدید به انتهای زنجیرهٔ حسابرسی زیر قفل سریال بدون شکاف."""
    cleaned_reason = entry.reason.strip()
    if entry.action in REQUIRE_REASON_ACTIONS and not cleaned_reason:
        msg = f"ثبت دلیل برای کنش حساس «{entry.action}» اجباری است."
        raise ValueError(msg)

    clean_meta = redact_value("metadata", entry.metadata)
    if not isinstance(clean_meta, dict):
        clean_meta = {}

    with transaction.atomic():
        serialize_on(AUDIT_CHAIN_LOCK)
        last = (
            AuditRecord.all_objects.select_for_update()
            .order_by("-sequence")
            .values("sequence", "record_hash")
            .first()
        )
        sequence = (int(last["sequence"]) + 1) if last else 1
        previous_hash = str(last["record_hash"]) if last else GENESIS_HASH

        req_meta = request_metadata(entry.request)
        row = AuditRecord.all_objects.create(
            sequence=sequence,
            action=entry.action,
            outcome=entry.outcome,
            actor_id=entry.actor_id,
            actor_label=entry.actor_label[:120],
            target_type=entry.target_type[:64],
            target_id=str(entry.target_id)[:64],
            reason=cleaned_reason[:500],
            metadata=clean_meta,
            request_id=req_meta["request_id"][:64],
            ip_address=req_meta["ip"] or None,
            user_agent=req_meta["user_agent"][:300],
            previous_hash=previous_hash,
            record_hash=uuid7_hex() + uuid7_hex(),
        )
        row.record_hash = compute_record_hash(
            previous_hash=previous_hash, payload=row.payload_for_hash()
        )
        row.save(update_fields=["record_hash", "updated_at"])

    logger.info(
        "audit_chain_appended",
        extra={"sequence": sequence, "action": entry.action, "outcome": entry.outcome},
    )
    return row


def verify_chain(*, limit: int | None = None) -> tuple[bool, int | None]:
    """راستی‌آزمایی پیوستگی و صحت هش رکوردهای زنجیرهٔ حسابرسی."""
    qs = AuditRecord.all_objects.order_by("sequence")
    if limit is not None:
        total = AuditRecord.all_objects.count()
        start_seq = max(total - limit + 1, 1)
        qs = qs.filter(sequence__gte=start_seq)
        if start_seq > 1:
            prev_row = (
                AuditRecord.all_objects.filter(sequence=start_seq - 1)
                .values_list("record_hash", flat=True)
                .first()
            )
            expected_prev = str(prev_row) if prev_row else GENESIS_HASH
        else:
            expected_prev = GENESIS_HASH
    else:
        expected_prev = GENESIS_HASH

    expected_seq: int | None = None
    for row in qs.iterator(chunk_size=500):
        if expected_seq is not None and row.sequence != expected_seq:
            return False, row.sequence
        expected_seq = row.sequence + 1
        if row.previous_hash != expected_prev:
            return False, row.sequence
        if not row.verify_integrity():
            return False, row.sequence
        expected_prev = row.record_hash
    return True, None


def create_audit_anchor() -> AuditAnchor:
    """ایجاد لنگر امضاشده از آخرین سرِ زنجیرهٔ حسابرسی."""
    last = AuditRecord.all_objects.order_by("-sequence").first()
    if last is None:
        msg = "زنجیرهٔ حسابرسی خالی است؛ امکان ساخت لنگر وجود ندارد."
        raise ValueError(msg)
    total = AuditRecord.all_objects.count()
    now = timezone.now()
    anchor = AuditAnchor(
        last_sequence=last.sequence,
        last_hash=last.record_hash,
        record_count=total,
        anchored_at=now,
        signature="",
    )
    anchor.signature = sign_payload(
        canonical_json(anchor.payload_for_signature()), namespace=ANCHOR_NAMESPACE
    )
    anchor.save()
    return anchor


def verify_anchors() -> tuple[bool, list[int]]:
    """راستی‌آزمایی تمام لنگرهای ثبت‌شده در برابر دستکاری یا کوتاه‌سازی انتهای زنجیره."""
    max_seq = int(AuditRecord.all_objects.aggregate(m=Max("sequence"))["m"] or 0)
    broken: list[int] = []
    for anchor in AuditAnchor.all_objects.order_by("-last_sequence")[:200]:
        sig_ok = verify_signature(
            canonical_json(anchor.payload_for_signature()),
            anchor.signature,
            namespace=ANCHOR_NAMESPACE,
        )
        if not sig_ok or anchor.last_sequence > max_seq:
            broken.append(anchor.last_sequence)
            continue
        matching_record = (
            AuditRecord.all_objects.filter(sequence=anchor.last_sequence)
            .values_list("record_hash", flat=True)
            .first()
        )
        if matching_record != anchor.last_hash:
            broken.append(anchor.last_sequence)
    return (not broken), broken


def record_audit_event(
    *,
    action: str,
    actor: Any = None,
    target_type: str = "",
    target_id: str = "",
    reason: str = "",
    metadata: dict[str, Any] | None = None,
    request: Any = None,
    outcome: str = AuditOutcome.SUCCESS,
) -> AuditRecord:
    """تابع کمکی یکپارچه برای ثبت رویداد حسابرسی از لایه‌های سرویس دامنه."""
    raw_req = getattr(request, "_request", request) if request is not None else None
    actor_id = getattr(actor, "id", None) if actor is not None else None
    actor_label = (
        str(getattr(actor, "display_name", "") or getattr(actor, "phone", ""))
        if actor is not None
        else ""
    )
    return record_audit(
        AuditEntry(
            action=action,
            outcome=outcome,
            actor_id=actor_id,
            actor_label=actor_label,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            metadata=metadata or {},
            request=raw_req if isinstance(raw_req, HttpRequest) else None,
        )
    )
