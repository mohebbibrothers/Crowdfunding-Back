"""مسیرهای API خیریه‌ها و قلک‌های عام خیریه."""

from __future__ import annotations

from django.urls import path

from apps.benefactors.views import (
    AdminBenefactorDetailView,
    AdminBenefactorListCreateView,
    AdminCharityJarDetailView,
    AdminCharityJarListCreateView,
    PublicBenefactorDetailView,
    PublicBenefactorListView,
    PublicCharityJarDetailView,
    PublicCharityJarListView,
)

urlpatterns = [
    path("benefactors", PublicBenefactorListView.as_view(), name="v1-benefactors-list"),
    path(
        "benefactors/<str:slug>",
        PublicBenefactorDetailView.as_view(),
        name="v1-benefactors-detail",
    ),
    path("jars", PublicCharityJarListView.as_view(), name="v1-jars-list"),
    path("jars/<str:identifier>", PublicCharityJarDetailView.as_view(), name="v1-jars-detail"),
    path(
        "admin/benefactors",
        AdminBenefactorListCreateView.as_view(),
        name="v1-admin-benefactors-list",
    ),
    path(
        "admin/benefactors/<str:benefactor_id>",
        AdminBenefactorDetailView.as_view(),
        name="v1-admin-benefactors-detail",
    ),
    path("admin/jars", AdminCharityJarListCreateView.as_view(), name="v1-admin-jars-list"),
    path(
        "admin/jars/<str:jar_id>",
        AdminCharityJarDetailView.as_view(),
        name="v1-admin-jars-detail",
    ),
]
