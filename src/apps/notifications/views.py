"""نماهای HTTP صندوق اعلان کاربر زیر ``/api/v1/me/notifications``."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import UserListCursorPagination
from apps.identity.permissions import authenticated_user
from apps.notifications.selectors import list_user_notifications
from apps.notifications.serializers import (
    MarkAllReadResponseSerializer,
    UserNotificationSerializer,
)
from apps.notifications.services import mark_all_notifications_read, mark_notification_read


class MeNotificationListView(APIView):
    """فهرست اعلان‌های درون‌برنامه‌ای خیر (شامل مژده‌های پیشرفت حرکت‌ها و رسیدها)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_me_notifications_list",
        summary="مشاهدهٔ فهرست اعلان‌ها و مژده‌های حرکت‌های همراهی‌شده",
        responses={200: UserNotificationSerializer(many=True)},
        tags=["Donor - Notifications"],
    )
    def get(self, request: Request) -> Response:
        """برگرداندن فهرست صفحه‌بندی‌شدهٔ اعلان‌های کاربر."""
        user = authenticated_user(request)
        unread_only = request.query_params.get("unread") == "true"
        qs = list_user_notifications(user_id=user.id, unread_only=unread_only)
        paginator = UserListCursorPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(UserNotificationSerializer(page, many=True).data)


class MeNotificationReadView(APIView):
    """علامت‌گذاری یک اعلان به‌عنوان خوانده‌شده."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_me_notifications_read",
        summary="ثبت مطالعهٔ یک اعلان",
        request=None,
        responses={200: UserNotificationSerializer},
        tags=["Donor - Notifications"],
    )
    def post(self, request: Request, notification_id: str) -> Response:
        """ثبت زمان مطالعهٔ اعلان."""
        user = authenticated_user(request)
        updated = mark_notification_read(user_id=user.id, notification_id=notification_id)
        return Response(UserNotificationSerializer(updated).data)


class MeNotificationReadAllView(APIView):
    """علامت‌گذاری تمام اعلان‌های کاربر به‌عنوان خوانده‌شده."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_me_notifications_read_all",
        summary="علامت‌گذاری تمام اعلان‌های من به‌عنوان خوانده‌شده",
        request=None,
        responses={200: MarkAllReadResponseSerializer},
        tags=["Donor - Notifications"],
    )
    def post(self, request: Request) -> Response:
        """خوانده کردن همهٔ اعلان‌های کاربر."""
        user = authenticated_user(request)
        count = mark_all_notifications_read(user_id=user.id)
        return Response({"marked_count": count})
