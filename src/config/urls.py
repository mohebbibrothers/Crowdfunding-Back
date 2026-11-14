"""مسیریابی ریشهٔ HTTP سامانه (تمام نقاط انتهایی دامنه زیر ``/api/v1/`` تجمیع شده‌اند)."""

from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.core.problems import not_found_handler, server_error_handler
from apps.core.views import docs_protected_wrapper, prometheus_metrics_view

v1_patterns = [
    path("", include("apps.core.api_urls")),
    path("", include("apps.audit.api_urls")),
    path("", include("apps.identity.api_urls")),
    path("", include("apps.notifications.api_urls")),
    path("", include("apps.benefactors.api_urls")),
    path("", include("apps.campaigns.api_urls")),
    path("", include("apps.ledger.api_urls")),
    path("", include("apps.contributions.api_urls")),
    path("", include("apps.reporting.api_urls")),
]

# مستندات تعاملی پیش از الگوهای دامنه قرار میگیرند تا هرگز توسط مسیرهای پارامتری بلعیده نشوند.
docs_patterns = [
    path(
        "api/v1/schema",
        docs_protected_wrapper(SpectacularAPIView.as_view(api_version="v1")),
        name="v1-openapi-schema",
    ),
    path(
        "api/v1/docs",
        docs_protected_wrapper(SpectacularSwaggerView.as_view(url_name="v1-openapi-schema")),
        name="v1-swagger-ui",
    ),
    path(
        "api/v1/redoc",
        docs_protected_wrapper(SpectacularRedocView.as_view(url_name="v1-openapi-schema")),
        name="v1-redoc",
    ),
]

urlpatterns = [
    *docs_patterns,
    path(settings.ADMIN_URL_PATH, admin.site.urls),
    path("metrics", prometheus_metrics_view, name="prometheus-metrics"),
    path("api/v1/", include((v1_patterns, "v1"))),
]

handler404 = not_found_handler
handler500 = server_error_handler
