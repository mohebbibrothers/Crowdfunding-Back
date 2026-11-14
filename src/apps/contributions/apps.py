"""پیکربندی اپلیکیشن مشارکت‌ها و ثبت مشترکین صندوق خروجی."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ContributionsConfig(AppConfig):
    """تنظیمات اپ ``apps.contributions``."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.contributions"
    verbose_name = _("مشارکت‌ها، درگاه پرداخت، شفافیت مرکل و داشبورد خیر")

    def ready(self) -> None:
        """ثبت پردازشگرهای Outbox و پورت‌های لایهٔ حقیقت وجه.

        چرا این ثبت‌ها اینجا و نه در بالای ماژول؟
            ``settlement`` و ``metrics`` نباید در زمان import به ``services``
            ارجاع بدهند (چرخهٔ واقعی: services → identity → audit →
            core.middleware → core.metrics → settlement → services). ثبت در
            ``ready`` یعنی لبه در زمان اجرا بسته می‌شود، نه در زمان import.
        """
        from apps.contributions.recurring import register_pledge_checkout_provider
        from apps.contributions.services import (
            checkout_pledge_installment,
            reconcile_one_abandoned_payment,
            register_contribution_outbox_handlers,
        )
        from apps.contributions.settlement import (
            build_money_truth_panel,
            register_recovery_engine,
        )
        from apps.core.metrics import register_money_truth_provider

        register_contribution_outbox_handlers()
        register_recovery_engine(reconcile_one_abandoned_payment)
        register_money_truth_provider(build_money_truth_panel)
        register_pledge_checkout_provider(checkout_pledge_installment)
