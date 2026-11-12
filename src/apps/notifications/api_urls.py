"""مسیرهای API اعلان‌های کاربر زیر ``/api/v1/me/notifications``."""

from __future__ import annotations

from django.urls import path

from apps.notifications.views import (
    MeNotificationListView,
    MeNotificationReadAllView,
    MeNotificationReadView,
)

urlpatterns = [
    path("me/notifications", MeNotificationListView.as_view(), name="v1-me-notifications"),
    path(
        "me/notifications/read-all",
        MeNotificationReadAllView.as_view(),
        name="v1-me-notifications-read-all",
    ),
    path(
        "me/notifications/<str:notification_id>/read",
        MeNotificationReadView.as_view(),
        name="v1-me-notifications-read",
    ),
]
