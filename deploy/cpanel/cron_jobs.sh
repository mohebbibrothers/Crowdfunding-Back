#!/usr/bin/env bash
# ==============================================================================
# Crowdfunding-Back — اجرای ایمن و بدون تداخل وظایف پس‌زمینه در Cron Jobs سی‌پنل
# استفاده از flock تضمین می‌کند که در صورت کندی موقت، دو پردازش همزمان اجرا نشوند.
#
# نمونه تنظیمات پیشنهادی در بخش Cron Jobs سی‌پنل نایترو:
#   * * * * *   /home/CPANEL_USER/Crowdfunding-Back/deploy/cpanel/cron_jobs.sh outbox   >> /home/CPANEL_USER/logs/cf-cron.log 2>&1
#   */2 * * * * /home/CPANEL_USER/Crowdfunding-Back/deploy/cpanel/cron_jobs.sh reap     >> /home/CPANEL_USER/logs/cf-cron.log 2>&1
#   0 * * * *   /home/CPANEL_USER/Crowdfunding-Back/deploy/cpanel/cron_jobs.sh anchor   >> /home/CPANEL_USER/logs/cf-cron.log 2>&1
#
# ── حلقهٔ نجات وجه: بدون این دو خط، پولی که «گم‌شده» به‌نظر می‌رسد هرگز پیدا نمی‌شود ──
#   */10 * * * * /home/CPANEL_USER/Crowdfunding-Back/deploy/cpanel/cron_jobs.sh recovery >> /home/CPANEL_USER/logs/cf-cron.log 2>&1
#   5 * * * *   /home/CPANEL_USER/Crowdfunding-Back/deploy/cpanel/cron_jobs.sh refunds  >> /home/CPANEL_USER/logs/cf-cron.log 2>&1
# ==============================================================================
set -euo pipefail

TASK="${1:-all}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LOCK_DIR="${REPO_ROOT}/tmp/locks"
mkdir -p "${LOCK_DIR}"

# تشخیص خودکار مفسر پایتون محیط مجازی سی‌پنل (virtualenv) یا .venv محلی
if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
    PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
elif [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
else
    PYTHON_BIN="$(command -v python3)"
fi

export PYTHONPATH="${REPO_ROOT}/src"
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.production}"

if [[ -f "${REPO_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/.env"
    set +a
fi

run_locked() {
    local lock_name="$1"
    shift
    flock -n "${LOCK_DIR}/${lock_name}.lock" "${PYTHON_BIN}" "${REPO_ROOT}/src/manage.py" "$@"
}

case "${TASK}" in
    outbox)
        run_locked "outbox" process_outbox --batch-size 100
        ;;
    reap)
        run_locked "reap" reap_expired
        ;;
    anchor)
        run_locked "anchor" anchor_audit_chain
        ;;
    recovery)
        # داوری پرداخت‌های رهاشده: آیا وجهی پس از انقضای رزرو نزد درگاه مانده است؟
        # هر ۱۰ دقیقه؛ دورهٔ تنفس (grace) در سیاست recovery.grace_minutes است.
        run_locked "recovery" reconcile_abandoned_payments --batch-size 200
        ;;
    refunds)
        # ارسال تعهدهای بازپرداخت به درگاه. مبالغ بالای recovery.auto_refund_max_rial
        # به‌جای ارسال خودکار، برای تأیید انسانی به وضعیت MANUAL می‌روند.
        run_locked "refunds" dispatch_pending_refunds --batch-size 100
        ;;
    all)
        run_locked "outbox" process_outbox --batch-size 100 || true
        run_locked "reap" reap_expired || true
        run_locked "anchor" anchor_audit_chain || true
        run_locked "recovery" reconcile_abandoned_payments --batch-size 200 || true
        run_locked "refunds" dispatch_pending_refunds --batch-size 100 || true
        ;;
    *)
        echo "Unknown cron task: ${TASK} (expected: outbox | reap | anchor | recovery | refunds | all)" >&2
        exit 2
        ;;
esac
