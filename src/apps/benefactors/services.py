"""سرویس‌های دامنه برای مدیریت خیریه‌ها و قلک‌های عام با ثبت ممیزی زنجیره‌ای."""

from __future__ import annotations

import secrets
import string
from typing import Any

from django.db import transaction

from apps.audit.choices import AuditAction
from apps.audit.services import record_audit_event
from apps.benefactors.models import Benefactor, CharityJar
from apps.core.cache import bump_epoch
from apps.core.errors import ConflictError, NotFoundError, ValidationError as DomainValidationError
from apps.identity.models import User
from apps.identity.validators import validate_iranian_iban

_SHORT_ALPHABET = string.ascii_lowercase + string.digits


def generate_unique_jar_short_code(length: int = 6) -> str:
    """تولید کد پیوندک کوتاه یکتا برای قلک عام خیریه."""
    for _ in range(20):
        candidate = "j" + "".join(secrets.choice(_SHORT_ALPHABET) for _ in range(length))
        if not CharityJar.objects.filter(short_code=candidate).exists():
            return candidate
    raise ConflictError("تولید کد کوتاه یکتا برای قلک ممکن نشد؛ دوباره تلاش کنید.")


@transaction.atomic
def create_benefactor(*, actor: User, data: dict[str, Any], request: Any = None) -> Benefactor:
    """ایجاد خیریه/نهاد جدید توسط مدیر با اعتبارسنجی شبا و ثبت ممیزی."""
    slug = str(data["slug"]).strip()
    if Benefactor.objects.filter(slug=slug).exists():
        raise ConflictError("نامک (slug) انتخاب‌شده پیش‌تر برای خیریهٔ دیگری ثبت شده است.")
    iban_raw = str(data.get("iban") or "").strip()
    iban = validate_iranian_iban(iban_raw) if iban_raw else ""

    benefactor = Benefactor.objects.create(
        name=str(data["name"]).strip(),
        slug=slug,
        registration_number=str(data.get("registration_number") or "").strip(),
        national_identifier=str(data.get("national_identifier") or "").strip(),
        province=str(data.get("province") or "").strip(),
        city=str(data.get("city") or "").strip(),
        short_bio=str(data.get("short_bio") or "").strip(),
        description=str(data.get("description") or "").strip(),
        logo_url=str(data.get("logo_url") or "").strip(),
        cover_url=str(data.get("cover_url") or "").strip(),
        website_url=str(data.get("website_url") or "").strip(),
        contact_phone=str(data.get("contact_phone") or "").strip(),
        iban=iban,
        bank_holder_name=str(data.get("bank_holder_name") or "").strip(),
        is_verified=bool(data.get("is_verified", True)),
        is_active=bool(data.get("is_active", True)),
        display_order=int(data.get("display_order", 100)),
    )
    record_audit_event(
        action=AuditAction.BENEFACTOR_SAVED,
        actor=actor,
        target_type="Benefactor",
        target_id=str(benefactor.id),
        metadata={"name": benefactor.name, "slug": benefactor.slug, "iban_set": bool(iban)},
        request=request,
    )
    transaction.on_commit(lambda: bump_epoch("benefactors"))
    return benefactor


@transaction.atomic
def update_benefactor(
    *,
    actor: User,
    benefactor_id: str,
    data: dict[str, Any],
    request: Any = None,
) -> Benefactor:
    """ویرایش مشخصات خیریه با ثبت تغییرات در زنجیرهٔ ممیزی."""
    benefactor = Benefactor.objects.select_for_update().filter(pk=benefactor_id).first()
    if benefactor is None:
        raise NotFoundError("خیریهٔ مورد نظر یافت نشد.")

    changed_fields: list[str] = []
    if "slug" in data:
        new_slug = str(data["slug"]).strip()
        if (
            new_slug != benefactor.slug
            and Benefactor.objects.filter(slug=new_slug).exclude(pk=benefactor.pk).exists()
        ):
            raise ConflictError("نامک انتخاب‌شده تکراری است.")
        benefactor.slug = new_slug
        changed_fields.append("slug")

    if "iban" in data:
        raw_iban = str(data.get("iban") or "").strip()
        benefactor.iban = validate_iranian_iban(raw_iban) if raw_iban else ""
        changed_fields.append("iban")

    str_fields = (
        "name",
        "registration_number",
        "national_identifier",
        "province",
        "city",
        "short_bio",
        "description",
        "logo_url",
        "cover_url",
        "website_url",
        "contact_phone",
        "bank_holder_name",
    )
    for field in str_fields:
        if field in data:
            setattr(benefactor, field, str(data[field] or "").strip())
            changed_fields.append(field)

    for bfield in ("is_verified", "is_active"):
        if bfield in data:
            setattr(benefactor, bfield, bool(data[bfield]))
            changed_fields.append(bfield)

    if "display_order" in data:
        benefactor.display_order = int(data["display_order"])
        changed_fields.append("display_order")

    if changed_fields:
        benefactor.save(update_fields=[*changed_fields, "updated_at"])
        record_audit_event(
            action=AuditAction.BENEFACTOR_SAVED,
            actor=actor,
            target_type="Benefactor",
            target_id=str(benefactor.id),
            metadata={"changed_fields": changed_fields},
            request=request,
        )
        transaction.on_commit(lambda: bump_epoch("benefactors"))
    return benefactor


@transaction.atomic
def deactivate_or_delete_benefactor(
    *,
    actor: User,
    benefactor_id: str,
    reason: str = "",
    request: Any = None,
) -> dict[str, Any]:
    """حذف فیزیکی خیریهٔ بدون سابقهٔ مالی یا غیرفعال‌سازی ایمن در صورت وجود حرکت/تراکنش."""
    benefactor = Benefactor.objects.select_for_update().filter(pk=benefactor_id).first()
    if benefactor is None:
        raise NotFoundError("خیریهٔ مورد نظر یافت نشد.")

    has_dependencies = (
        benefactor.total_raised_rial > 0
        or benefactor.jars.exists()
        or (getattr(benefactor, "campaigns", None) is not None and benefactor.campaigns.exists())
    )
    if has_dependencies:
        benefactor.is_active = False
        benefactor.save(update_fields=["is_active", "updated_at"])
        record_audit_event(
            action=AuditAction.BENEFACTOR_SAVED,
            actor=actor,
            target_type="Benefactor",
            target_id=str(benefactor.id),
            reason=reason or "غیرفعال‌سازی ایمن به دلیل وجود سابقهٔ حرکت یا قلک",
            metadata={"deactivated_only": True},
            request=request,
        )
        transaction.on_commit(lambda: bump_epoch("benefactors"))
        return {"deleted": False, "deactivated": True, "id": str(benefactor.id)}

    bid = str(benefactor.id)
    bname = benefactor.name
    benefactor.delete()
    record_audit_event(
        action=AuditAction.BENEFACTOR_SAVED,
        actor=actor,
        target_type="Benefactor",
        target_id=bid,
        reason=reason or "حذف خیریه بدون سابقه مالی",
        metadata={"deleted": True, "name": bname},
        request=request,
    )
    transaction.on_commit(lambda: bump_epoch("benefactors"))
    return {"deleted": True, "deactivated": False, "id": bid}


@transaction.atomic
def create_charity_jar(*, actor: User, data: dict[str, Any], request: Any = None) -> CharityJar:
    """ایجاد قلک عام برای یک خیریه توسط مدیر."""
    benefactor = Benefactor.objects.filter(pk=data["benefactor_id"]).first()
    if benefactor is None:
        raise NotFoundError("خیریهٔ مورد نظر یافت نشد.")
    slug = str(data["slug"]).strip()
    if CharityJar.objects.filter(slug=slug).exists():
        raise ConflictError("نامک (slug) قلک تکراری است.")

    min_rial = int(data.get("min_amount_rial", 100_000))
    max_rial = int(data.get("max_amount_rial", 5_000_000_000))
    if min_rial < 10_000 or max_rial < min_rial:
        raise DomainValidationError("بازهٔ حداقل و حداکثر مبلغ ریالی قلک نامعتبر است.")

    short_code = str(data.get("short_code") or "").strip() or generate_unique_jar_short_code()
    if CharityJar.objects.filter(short_code=short_code).exists():
        raise ConflictError("کد پیوندک کوتاه انتخاب‌شده تکراری است.")

    jar = CharityJar.objects.create(
        benefactor=benefactor,
        title=str(data["title"]).strip(),
        slug=slug,
        short_code=short_code,
        description=str(data.get("description") or "").strip(),
        suggested_amounts_rial=list(
            data.get("suggested_amounts_rial") or [500_000, 1_000_000, 5_000_000, 10_000_000]
        ),
        min_amount_rial=min_rial,
        max_amount_rial=max_rial,
        monthly_goal_rial=int(data.get("monthly_goal_rial", 0)),
        is_active=bool(data.get("is_active", True)),
    )
    record_audit_event(
        action=AuditAction.BENEFACTOR_SAVED,
        actor=actor,
        target_type="CharityJar",
        target_id=str(jar.id),
        metadata={"jar_created": True, "slug": jar.slug, "benefactor_id": str(benefactor.id)},
        request=request,
    )
    transaction.on_commit(lambda: bump_epoch("benefactors"))
    transaction.on_commit(lambda: bump_epoch("jars"))
    return jar


@transaction.atomic
def update_charity_jar(
    *,
    actor: User,
    jar_id: str,
    data: dict[str, Any],
    request: Any = None,
) -> CharityJar:
    """ویرایش تنظیمات قلک عام خیریه."""
    jar = (
        CharityJar.objects.select_for_update()
        .select_related("benefactor")
        .filter(pk=jar_id)
        .first()
    )
    if jar is None:
        raise NotFoundError("قلک عام مورد نظر یافت نشد.")

    changed: list[str] = []
    for sfield in ("title", "description"):
        if sfield in data:
            setattr(jar, sfield, str(data[sfield] or "").strip())
            changed.append(sfield)

    if "suggested_amounts_rial" in data:
        jar.suggested_amounts_rial = [int(x) for x in data["suggested_amounts_rial"]]
        changed.append("suggested_amounts_rial")

    for ifield in ("min_amount_rial", "max_amount_rial", "monthly_goal_rial"):
        if ifield in data:
            setattr(jar, ifield, int(data[ifield]))
            changed.append(ifield)

    if jar.min_amount_rial < 10_000 or jar.max_amount_rial < jar.min_amount_rial:
        raise DomainValidationError("بازهٔ حداقل و حداکثر مبلغ ریالی قلک نامعتبر است.")

    if "is_active" in data:
        jar.is_active = bool(data["is_active"])
        changed.append("is_active")

    if changed:
        jar.save(update_fields=[*changed, "updated_at"])
        record_audit_event(
            action=AuditAction.BENEFACTOR_SAVED,
            actor=actor,
            target_type="CharityJar",
            target_id=str(jar.id),
            metadata={"jar_updated": True, "changed_fields": changed},
            request=request,
        )
        transaction.on_commit(lambda: bump_epoch("benefactors"))
        transaction.on_commit(lambda: bump_epoch("jars"))
    return jar
