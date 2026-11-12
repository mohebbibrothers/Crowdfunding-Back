# syntax=docker/dockerfile:1.7
# ==============================================================================
# Crowdfunding-Back — تصویر کانتینر چندمرحله‌ای، کم‌حجم و غیرریشه (Non-Root)
# ==============================================================================

FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        default-libmysqlclient-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY README.md LICENSE ./
RUN uv sync --frozen --no-dev

# ── مرحلهٔ اجرایی کمینه (Runtime) ────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    DJANGO_SETTINGS_MODULE="config.settings.production"

RUN apt-get update && apt-get install -y --no-install-recommends \
        libmariadb3 \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 appgroup \
    && useradd --uid 10001 --gid appgroup --shell /usr/sbin/nologin --create-home appuser

WORKDIR /app
COPY --from=builder --chown=appuser:appgroup /app /app

RUN mkdir -p /app/staticfiles && chown -R appuser:appgroup /app/staticfiles

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=3)" || exit 1

CMD ["gunicorn", "config.wsgi:application", "--chdir", "/app/src", "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "2", "--timeout", "60", "--max-requests", "1000", "--max-requests-jitter", "100"]
