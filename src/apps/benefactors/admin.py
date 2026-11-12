"""ثبت مدل‌های خیریه و قلک عام در پنل ادمین جنگو."""

from __future__ import annotations

from django.contrib import admin

from apps.benefactors.models import Benefactor, CharityJar


@admin.register(Benefactor)
class BenefactorAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """مدیریت خیریه‌ها."""

    list_display = (
        "name",
        "slug",
        "province",
        "is_verified",
        "is_active",
        "total_raised_rial",
    )
    list_filter = ("is_verified", "is_active", "province")
    search_fields = ("name", "slug", "registration_number")


@admin.register(CharityJar)
class CharityJarAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """مدیریت قلک‌های عام خیریه."""

    list_display = ("title", "benefactor", "short_code", "total_raised_rial", "is_active")
    list_filter = ("is_active",)
    search_fields = ("title", "slug", "short_code")
