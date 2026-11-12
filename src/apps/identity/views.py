"""نماهای HTTP احراز هویت، مدیریت نشست‌ها، پروفایل، TOTP کارکنان و مدیریت کاربران."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import StaffTableCursorPagination
from apps.identity.choices import OtpPurpose
from apps.identity.permissions import (
    HasFreshMfa,
    IsFinanceOrSuperAdmin,
    IsStaffRole,
    authenticated_user,
    resolve_active_session,
)
from apps.identity.selectors import (
    get_staff_mfa_status,
    list_active_sessions_for_user,
    list_admin_users,
    list_auth_risk_signals,
)
from apps.identity.serializers import (
    AdminPhoneRevealInputSerializer,
    AdminRoleChangeInputSerializer,
    AdminUserOutputSerializer,
    AuthRiskReviewInputSerializer,
    AuthRiskSignalOutputSerializer,
    AuthTokensOutputSerializer,
    MfaCodeInputSerializer,
    MfaConfirmOutputSerializer,
    MfaSetupOutputSerializer,
    MfaStatusOutputSerializer,
    OtpRequestAcceptedSerializer,
    OtpRequestInputSerializer,
    OtpVerifyInputSerializer,
    ProfileUpdateInputSerializer,
    SessionItemOutputSerializer,
    StaffPasswordLoginInputSerializer,
    TokenRefreshInputSerializer,
    UserMeOutputSerializer,
)
from apps.identity.services import (
    OTP_TTL_SECONDS,
    IssuedAuthTokens,
    begin_staff_totp_setup,
    change_user_role,
    confirm_staff_totp_setup,
    establish_dual_session,
    logout_current_session,
    request_otp,
    reveal_donor_phone,
    review_auth_risk_signal,
    revoke_other_sessions,
    revoke_user_session,
    rotate_refresh_token,
    staff_password_login,
    update_user_profile,
    verify_otp_and_get_user,
    verify_staff_mfa,
)
from apps.identity.throttles import OtpRequestThrottle, OtpVerifyThrottle


def _format_auth_bundle(bundle: IssuedAuthTokens) -> dict[str, Any]:
    return {
        "access_token": bundle.access_token,
        "refresh_token": bundle.refresh_token,
        "session_id": bundle.session.id,
        "mfa_required": bundle.mfa_required,
        "user": UserMeOutputSerializer(bundle.user).data,
    }


class OtpRequestView(APIView):
    """ارسال کد ۵ رقمی پیامکی برای ورود یا ثبت‌نام (پاسخ یکسان ضد شمارش کاربران)."""

    permission_classes = [AllowAny]
    throttle_classes = [OtpRequestThrottle]

    @extend_schema(
        operation_id="v1_auth_otp_request",
        summary="درخواست کد یک‌بارمصرف پیامکی (ورود / ثبت‌نام)",
        request=OtpRequestInputSerializer,
        responses={202: OtpRequestAcceptedSerializer},
        tags=["Auth"],
    )
    def post(self, request: Request) -> Response:
        """ثبت چالش OTP و قرار دادن پیامک در صندوق خروجی."""
        serializer = OtpRequestInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_otp(
            phone_raw=serializer.validated_data["phone"],
            purpose=OtpPurpose.LOGIN,
            request=request._request,
        )
        return Response(
            {
                "status": "accepted",
                "ttl_seconds": OTP_TTL_SECONDS,
                "message": "کد تأیید ۵ رقمی به شماره موبایل ارسال شد.",
            },
            status=202,
        )


class OtpVerifyView(APIView):
    """تأیید کد یک‌بارمصرف و صدور هم‌زمان کوکی HttpOnly و جفت توکن SessionAwareJWT."""

    permission_classes = [AllowAny]
    throttle_classes = [OtpVerifyThrottle]

    @extend_schema(
        operation_id="v1_auth_otp_verify",
        summary="تأیید کد پیامکی و دریافت نشست (Cookie + JWT)",
        request=OtpVerifyInputSerializer,
        responses={200: AuthTokensOutputSerializer},
        tags=["Auth"],
    )
    def post(self, request: Request) -> Response:
        """اعتبارسنجی کد و ایجاد نشست دوگانه."""
        serializer = OtpVerifyInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = verify_otp_and_get_user(
            phone_raw=serializer.validated_data["phone"],
            code_raw=serializer.validated_data["code"],
            purpose=OtpPurpose.LOGIN,
            request=request._request,
        )
        bundle = establish_dual_session(user=user, request=request._request)
        return Response(_format_auth_bundle(bundle), status=200)


class StaffPasswordLoginView(APIView):
    """ورود کارکنان با گذرواژهٔ Argon2 (پس از آن برای پنل عملیاتی تأیید TOTP الزامی است)."""

    permission_classes = [AllowAny]
    throttle_classes = [OtpVerifyThrottle]

    @extend_schema(
        operation_id="v1_auth_staff_password_login",
        summary="ورود کارکنان با شماره موبایل و گذرواژه",
        request=StaffPasswordLoginInputSerializer,
        responses={200: AuthTokensOutputSerializer},
        tags=["Auth"],
    )
    def post(self, request: Request) -> Response:
        """بررسی گذرواژه و ایجاد نشست اولیهٔ کارمند."""
        serializer = StaffPasswordLoginInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bundle = staff_password_login(
            phone_raw=serializer.validated_data["phone"],
            password=serializer.validated_data["password"],
            request=request._request,
        )
        return Response(_format_auth_bundle(bundle), status=200)


class TokenRefreshView(APIView):
    """نوسازی چرخشی جفت توکن دسترسی و تشخیص بازپخش توکن مسروقه."""

    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="v1_auth_token_refresh",
        summary="نوسازی چرخشی توکن JWT با تشخیص سرقت توکن",
        request=TokenRefreshInputSerializer,
        responses={200: AuthTokensOutputSerializer},
        tags=["Auth"],
    )
    def post(self, request: Request) -> Response:
        """اجرای چرخش refresh_jti روی نشست فعال."""
        serializer = TokenRefreshInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bundle = rotate_refresh_token(
            raw_refresh_token=serializer.validated_data["refresh_token"],
            request=request._request,
        )
        return Response(_format_auth_bundle(bundle), status=200)


class LogoutView(APIView):
    """خروج از نشست فعلی و ابطال هم‌زمان کوکی و توکن JWT آن."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_auth_logout",
        summary="خروج از نشست جاری",
        request=None,
        responses={204: None},
        tags=["Auth"],
    )
    def post(self, request: Request) -> Response:
        """بستن نشست فعلی."""
        user = authenticated_user(request)
        session_obj = resolve_active_session(request)
        logout_current_session(user=user, session_obj=session_obj, request=request._request)
        return Response(status=204)


class LogoutOthersView(APIView):
    """خروج از تمام دستگاه‌های دیگر با حفظ نشست جاری."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_auth_logout_others",
        summary="ابطال تمام نشست‌های دیگر به‌جز دستگاه فعلی",
        request=None,
        responses={
            200: {
                "type": "object",
                "properties": {"revoked_count": {"type": "integer"}},
                "required": ["revoked_count"],
            }
        },
        tags=["Auth"],
    )
    def post(self, request: Request) -> Response:
        """ابطال سایر نشست‌ها."""
        user = authenticated_user(request)
        current = resolve_active_session(request)
        revoked = revoke_other_sessions(
            user=user, current_session=current, request=request._request
        )
        return Response({"revoked_count": revoked})


class MeProfileView(APIView):
    """مشاهده و تکمیل پروفایل کاربر جاری."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_me_profile_retrieve",
        summary="مشاهدهٔ اطلاعات حساب و پروفایل کاربر جاری",
        responses={200: UserMeOutputSerializer},
        tags=["Donor - Profile & Sessions"],
    )
    def get(self, request: Request) -> Response:
        """برگرداندن پروفایل کاربر جاری."""
        user = authenticated_user(request)
        return Response(UserMeOutputSerializer(user).data)

    @extend_schema(
        operation_id="v1_me_profile_update",
        summary="تکمیل یا ویرایش پروفایل خیر (نام، استان، شهر، کد ملی رمزشده)",
        request=ProfileUpdateInputSerializer,
        responses={200: UserMeOutputSerializer},
        tags=["Donor - Profile & Sessions"],
    )
    def patch(self, request: Request) -> Response:
        """به‌روزرسانی فیلدهای پروفایل."""
        serializer = ProfileUpdateInputSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = authenticated_user(request)
        updated = update_user_profile(user=user, **serializer.validated_data)
        return Response(UserMeOutputSerializer(updated).data)


class MeSessionListView(APIView):
    """مشاهدهٔ فهرست دستگاه‌ها و نشست‌های فعال کاربر."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_me_sessions_list",
        summary="مشاهدهٔ فهرست دستگاه‌ها و نشست‌های فعال من",
        responses={200: SessionItemOutputSerializer(many=True)},
        tags=["Donor - Profile & Sessions"],
    )
    def get(self, request: Request) -> Response:
        """برگرداندن نشست‌های فعال کاربر."""
        user = authenticated_user(request)
        current = resolve_active_session(request)
        items = list_active_sessions_for_user(
            user=user, current_session_id=str(current.id) if current else None
        )
        return Response(SessionItemOutputSerializer(items, many=True).data)


class MeSessionRevokeView(APIView):
    """ابطال یک نشست خاص از فهرست دستگاه‌های کاربر."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_me_sessions_revoke",
        summary="ابطال یک نشست مشخص از راه دور",
        request=None,
        responses={204: None},
        tags=["Donor - Profile & Sessions"],
    )
    def post(self, request: Request, session_id: str) -> Response:
        """ابطال آنی نشست انتخاب‌شده."""
        user = authenticated_user(request)
        current = resolve_active_session(request)
        revoke_user_session(
            user=user,
            target_session_id=session_id,
            current_session=current,
            request=request._request,
        )
        return Response(status=204)


# ── مسیرهای تأیید دومرحله‌ای کارکنان (TOTP MFA) ─────────────────────────────


class StaffMfaStatusView(APIView):
    """وضعیت ثبت‌نام و تأیید TOTP برای کارمند واردشده."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_auth_mfa_status",
        summary="مشاهدهٔ وضعیت تأیید دومرحله‌ای کارمند",
        responses={200: MfaStatusOutputSerializer},
        tags=["Auth - Staff MFA"],
    )
    def get(self, request: Request) -> Response:
        """برگرداندن وضعیت عامل دوم نشست جاری."""
        user = authenticated_user(request)
        current = resolve_active_session(request)
        return Response(get_staff_mfa_status(user=user, current_session=current))


class StaffMfaTotpSetupView(APIView):
    """دریافت کلید مخفی و تصویر QR SVG برای ثبت در اپلیکیشن Authenticator."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_auth_mfa_totp_setup",
        summary="شروع راه‌اندازی TOTP کارمند و دریافت QR SVG",
        request=None,
        responses={200: MfaSetupOutputSerializer},
        tags=["Auth - Staff MFA"],
    )
    def post(self, request: Request) -> Response:
        """ساخت دستگاه TOTP اولیه."""
        user = authenticated_user(request)
        data = begin_staff_totp_setup(user=user)
        return Response(data)


class StaffMfaTotpConfirmView(APIView):
    """تأیید کد ۶ رقمی اولیه، فعال‌سازی دستگاه و دریافت ۱۰ کد بازیابی."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_auth_mfa_totp_confirm",
        summary="تأیید نهایی دستگاه TOTP و دریافت کدهای بازیابی",
        request=MfaCodeInputSerializer,
        responses={200: MfaConfirmOutputSerializer},
        tags=["Auth - Staff MFA"],
    )
    def post(self, request: Request) -> Response:
        """فعال‌سازی TOTP و صدور کدهای بازیابی."""
        serializer = MfaCodeInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticated_user(request)
        current = resolve_active_session(request)
        codes = confirm_staff_totp_setup(
            user=user,
            session_obj=current,
            code=serializer.validated_data["code"],
            request=request._request,
        )
        return Response({"enrolled": True, "recovery_codes": codes})


class StaffMfaVerifyView(APIView):
    """تأیید TOTP یا کد بازیابی روی نشست فعال (هم برای ورود و هم Step-Up تازه)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_auth_mfa_verify",
        summary="تأیید کد دومرحله‌ای روی نشست فعال یا ارتقای Step-Up",
        request=MfaCodeInputSerializer,
        responses={200: MfaStatusOutputSerializer},
        tags=["Auth - Staff MFA"],
    )
    def post(self, request: Request) -> Response:
        """ثبت مهر زمان تأیید MFA روی نشست جاری."""
        serializer = MfaCodeInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticated_user(request)
        current = resolve_active_session(request)
        verified_session = verify_staff_mfa(
            user=user,
            session_obj=current,
            code=serializer.validated_data["code"],
            request=request._request,
        )
        return Response(get_staff_mfa_status(user=user, current_session=verified_session))


# ── مدیریت کاربران، نقش‌ها و حریم خصوصی در پنل ادمین ─────────────────────────


class AdminUserListView(APIView):
    """فهرست کاربران سامانه با شماره تلفن پوشانده‌شده برای کارکنان."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        operation_id="v1_admin_users_list",
        summary="فهرست کاربران سامانه (با تلفن پوشانده در حالت عادی)",
        parameters=[
            OpenApiParameter(name="q", type=str, required=False),
            OpenApiParameter(name="role", type=str, required=False),
        ],
        responses={200: AdminUserOutputSerializer(many=True)},
        tags=["Admin - Identity"],
    )
    def get(self, request: Request) -> Response:
        """واکشی فهرست صفحه‌بندی‌شدهٔ کاربران."""
        qs = list_admin_users(
            search=request.query_params.get("q", "").strip(),
            role=request.query_params.get("role", "").strip(),
        )
        paginator = StaffTableCursorPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(AdminUserOutputSerializer(page, many=True).data)


class AdminUserRoleUpdateView(APIView):
    """تغییر نقش کاربری توسط مدیر ارشد همراه با تأیید تازهٔ MFA و ثبت دلیل."""

    permission_classes = [IsFinanceOrSuperAdmin, HasFreshMfa]

    @extend_schema(
        operation_id="v1_admin_users_role_update",
        summary="تغییر نقش کاربر با الزام Step-Up MFA و ثبت دلیل",
        request=AdminRoleChangeInputSerializer,
        responses={200: AdminUserOutputSerializer},
        tags=["Admin - Identity"],
    )
    def post(self, request: Request, user_id: str) -> Response:
        """اعمال تغییر نقش و ثبت در حسابرسی."""
        serializer = AdminRoleChangeInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        updated = change_user_role(
            actor=actor,
            target_user_id=user_id,
            new_role=serializer.validated_data["role"],
            reason=serializer.validated_data["reason"],
            request=request._request,
        )
        return Response(AdminUserOutputSerializer(updated).data)


class AdminUserPhoneRevealView(APIView):
    """افشای کنترل‌شده و ممیزی‌شدهٔ شماره تلفن کامل خیر فقط با Step-Up MFA و دلیل."""

    permission_classes = [IsStaffRole, HasFreshMfa]

    @extend_schema(
        operation_id="v1_admin_users_reveal_phone",
        summary="مشاهدهٔ شماره موبایل کامل خیر با ثبت هدف ممیزی و Step-Up MFA",
        request=AdminPhoneRevealInputSerializer,
        responses={
            200: {
                "type": "object",
                "properties": {"phone": {"type": "string"}},
                "required": ["phone"],
            }
        },
        tags=["Admin - Identity"],
    )
    def post(self, request: Request, user_id: str) -> Response:
        """ثبت دلیل در زنجیرهٔ حسابرسی و برگرداندن شمارهٔ کامل."""
        serializer = AdminPhoneRevealInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        phone = reveal_donor_phone(
            actor=actor,
            target_user_id=user_id,
            reason=serializer.validated_data["reason"],
            request=request._request,
        )
        return Response({"phone": phone})


class AdminAuthRiskListView(APIView):
    """فهرست سیگنال‌های ریسک امنیتی احراز هویت."""

    permission_classes = [IsFinanceOrSuperAdmin]

    @extend_schema(
        operation_id="v1_admin_auth_risks_list",
        summary="فهرست سیگنال‌های ریسک امنیتی ورود و توکن‌ها",
        parameters=[OpenApiParameter(name="status", type=str, required=False)],
        responses={200: AuthRiskSignalOutputSerializer(many=True)},
        tags=["Admin - Identity"],
    )
    def get(self, request: Request) -> Response:
        """واکشی صفحه‌بندی‌شدهٔ سیگنال‌های ریسک."""
        qs = list_auth_risk_signals(status=request.query_params.get("status", "").strip())
        paginator = StaffTableCursorPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            AuthRiskSignalOutputSerializer(page, many=True).data
        )


class AdminAuthRiskReviewView(APIView):
    """ثبت نتیجهٔ بررسی یک سیگنال ریسک امنیتی."""

    permission_classes = [IsFinanceOrSuperAdmin]

    @extend_schema(
        operation_id="v1_admin_auth_risks_review",
        summary="بررسی و تعیین وضعیت سیگنال ریسک احراز هویت",
        request=AuthRiskReviewInputSerializer,
        responses={200: AuthRiskSignalOutputSerializer},
        tags=["Admin - Identity"],
    )
    def post(self, request: Request, signal_id: str) -> Response:
        """ذخیرهٔ وضعیت بررسی سیگنال."""
        serializer = AuthRiskReviewInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        updated = review_auth_risk_signal(
            actor=actor,
            signal_id=signal_id,
            new_status=serializer.validated_data["status"],
            note=serializer.validated_data["note"],
        )
        return Response(AuthRiskSignalOutputSerializer(updated).data)
