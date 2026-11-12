#!/usr/bin/env bash
# ==============================================================================
# Crowdfunding-Back — اسکریپت استقرار بدون قطعی (Zero-Downtime) روی سی‌پنل نایترو
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
    PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
    PIP_BIN="${VIRTUAL_ENV}/bin/pip"
elif [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
    PIP_BIN="${REPO_ROOT}/.venv/bin/pip"
else
    echo "Error: Activate your cPanel Python virtualenv (source ~/virtualenv/.../bin/activate) first." >&2
    exit 1
fi

export PYTHONPATH="${REPO_ROOT}/src"
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.production}"

if [[ -f "${REPO_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/.env"
    set +a
fi

echo "==> [1/6] Installing production dependencies..."
"${PIP_BIN}" install --upgrade pip
"${PIP_BIN}" install --no-cache-dir .

echo "==> [2/6] Running production security & configuration check..."
"${PYTHON_BIN}" src/manage.py check --deploy --fail-level ERROR

echo "==> [3/6] Applying MariaDB schema migrations..."
"${PYTHON_BIN}" src/manage.py migrate --noinput

echo "==> [4/6] Ensuring atomic database cache table exists..."
"${PYTHON_BIN}" src/manage.py createcachetable --database=cache

echo "==> [5/6] Collecting compressed static assets (WhiteNoise)..."
"${PYTHON_BIN}" src/manage.py collectstatic --noinput

echo "==> [6/6] Signaling CloudLinux Passenger graceful restart..."
mkdir -p "${REPO_ROOT}/tmp"
touch "${REPO_ROOT}/tmp/restart.txt"

echo "Deployment completed successfully."
