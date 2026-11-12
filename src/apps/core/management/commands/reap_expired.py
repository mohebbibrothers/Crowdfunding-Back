"""فرمان آزادسازی رزروهای ۱۵ دقیقه‌ای منقضی‌شده و پاک‌سازی رکوردهای موقت منقضی (Cron Reaper)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.contributions.models import ExpressContributionIntent
from apps.contributions.services import release_expired_share_holds
from apps.core.idempotency import purge_expired_idempotency_keys
from apps.identity.models import OtpChallenge, UserSession


class Command(BaseCommand):
    """آزادسازی اتمیک سهم‌های رزرو منقضی و پاک‌سازی جدول‌های موقت."""

    help = "آزادسازی رزروهای ۱۵ دقیقه‌ای سهم و پاک‌سازی رکوردهای منقضی Idempotency/OTP"

    def handle(self, *args: Any, **options: Any) -> None:
        del args, options
        now = timezone.now()
        released_holds = release_expired_share_holds()
        idem_deleted = purge_expired_idempotency_keys()
        otp_deleted, _ = OtpChallenge.objects.filter(
            expires_at__lt=now - timedelta(days=1)
        ).delete()
        intent_deleted, _ = ExpressContributionIntent.objects.filter(
            expires_at__lt=now - timedelta(days=1)
        ).delete()
        sess_deleted, _ = UserSession.all_objects.filter(
            revoked_at__lt=now - timedelta(days=30)
        ).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Reaped: share_holds_released={released_holds} idempotency={idem_deleted} "
                f"otp={otp_deleted} express_intents={intent_deleted} old_sessions={sess_deleted}"
            )
        )
