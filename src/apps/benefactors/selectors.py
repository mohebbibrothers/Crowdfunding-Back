"""سلکتورهای خوانشی خیریه‌ها و قلک‌های عام."""

from __future__ import annotations

from django.db.models import Prefetch, QuerySet

from apps.benefactors.models import Benefactor, CharityJar
from apps.core.errors import NotFoundError


def list_public_benefactors(
    *, province: str | None = None, search: str | None = None
) -> QuerySet[Benefactor]:
    """فهرست خیریه‌های فعال برای نمایش عمومی همراه با قلک‌های فعال."""
    active_jars = CharityJar.objects.filter(is_active=True).order_by("created_at")
    qs = Benefactor.objects.filter(is_active=True).prefetch_related(
        Prefetch("jars", queryset=active_jars, to_attr="prefetched_active_jars")
    )
    if province:
        qs = qs.filter(province=province)
    if search:
        qs = qs.filter(name__icontains=search)
    return qs.order_by("display_order", "-total_raised_rial", "-id")


def get_public_benefactor_by_slug(*, slug: str) -> Benefactor:
    """دریافت جزئیات عمومی خیریه از روی نامک."""
    active_jars = CharityJar.objects.filter(is_active=True).order_by("created_at")
    benefactor = (
        Benefactor.objects.filter(slug=slug, is_active=True)
        .prefetch_related(Prefetch("jars", queryset=active_jars, to_attr="prefetched_active_jars"))
        .first()
    )
    if benefactor is None:
        raise NotFoundError("خیریهٔ مورد نظر یافت نشد.")
    return benefactor


def list_admin_benefactors(*, include_inactive: bool = True) -> QuerySet[Benefactor]:
    """فهرست مدیریتی خیریه‌ها."""
    qs = Benefactor.objects.all()
    if not include_inactive:
        qs = qs.filter(is_active=True)
    return qs.order_by("display_order", "-created_at", "-id")


def list_public_jars(*, benefactor_slug: str | None = None) -> QuerySet[CharityJar]:
    """فهرست عمومی قلک‌های عام فعال."""
    qs = CharityJar.objects.select_related("benefactor").filter(
        is_active=True,
        benefactor__is_active=True,
    )
    if benefactor_slug:
        qs = qs.filter(benefactor__slug=benefactor_slug)
    return qs.order_by("-total_raised_rial", "-created_at", "-id")


def get_public_jar_by_slug_or_code(*, identifier: str) -> CharityJar:
    """واکشی قلک عام از روی نامک یا کد پیوندک کوتاه."""
    jar = (
        CharityJar.objects.select_related("benefactor")
        .filter(is_active=True, benefactor__is_active=True)
        .filter(slug=identifier)
        .first()
    )
    if jar is None:
        jar = (
            CharityJar.objects.select_related("benefactor")
            .filter(is_active=True, benefactor__is_active=True, short_code=identifier)
            .first()
        )
    if jar is None:
        raise NotFoundError("قلک عام مورد نظر یافت نشد یا غیرفعال است.")
    return jar
