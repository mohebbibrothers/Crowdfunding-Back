"""مسیرهای API ماژول هویت، نشست‌ها، MFA کارکنان و مدیریت کاربران زیر ``/api/v1/``."""

from __future__ import annotations

from django.urls import path

from apps.identity.views import (
    AdminAuthRiskListView,
    AdminAuthRiskReviewView,
    AdminUserListView,
    AdminUserPhoneRevealView,
    AdminUserRoleUpdateView,
    LogoutOthersView,
    LogoutView,
    MeProfileView,
    MeSessionListView,
    MeSessionRevokeView,
    OtpRequestView,
    OtpVerifyView,
    StaffMfaStatusView,
    StaffMfaTotpConfirmView,
    StaffMfaTotpSetupView,
    StaffMfaVerifyView,
    StaffPasswordLoginView,
    TokenRefreshView,
)

urlpatterns = [
    path("auth/otp/request", OtpRequestView.as_view(), name="v1-auth-otp-request"),
    path("auth/otp/verify", OtpVerifyView.as_view(), name="v1-auth-otp-verify"),
    path(
        "auth/staff/password-login",
        StaffPasswordLoginView.as_view(),
        name="v1-auth-staff-password-login",
    ),
    path("auth/token/refresh", TokenRefreshView.as_view(), name="v1-auth-token-refresh"),
    path("auth/logout", LogoutView.as_view(), name="v1-auth-logout"),
    path("auth/logout-others", LogoutOthersView.as_view(), name="v1-auth-logout-others"),
    path("auth/mfa/status", StaffMfaStatusView.as_view(), name="v1-auth-mfa-status"),
    path("auth/mfa/totp/setup", StaffMfaTotpSetupView.as_view(), name="v1-auth-mfa-setup"),
    path("auth/mfa/totp/confirm", StaffMfaTotpConfirmView.as_view(), name="v1-auth-mfa-confirm"),
    path("auth/mfa/verify", StaffMfaVerifyView.as_view(), name="v1-auth-mfa-verify"),
    path("me", MeProfileView.as_view(), name="v1-me-profile"),
    path("me/sessions", MeSessionListView.as_view(), name="v1-me-sessions"),
    path(
        "me/sessions/<str:session_id>/revoke",
        MeSessionRevokeView.as_view(),
        name="v1-me-sessions-revoke",
    ),
    path("admin/users", AdminUserListView.as_view(), name="v1-admin-users-list"),
    path(
        "admin/users/<str:user_id>/role",
        AdminUserRoleUpdateView.as_view(),
        name="v1-admin-users-role",
    ),
    path(
        "admin/users/<str:user_id>/reveal-phone",
        AdminUserPhoneRevealView.as_view(),
        name="v1-admin-users-reveal-phone",
    ),
    path("admin/auth/risk-signals", AdminAuthRiskListView.as_view(), name="v1-admin-auth-risks"),
    path(
        "admin/auth/risk-signals/<str:signal_id>/review",
        AdminAuthRiskReviewView.as_view(),
        name="v1-admin-auth-risks-review",
    ),
]
