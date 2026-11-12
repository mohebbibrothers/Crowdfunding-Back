# ==============================================================================
# Crowdfunding-Back — میانبرهای توسعه، کنترل کیفیت، طرحواره و اجرای محلی
# ==============================================================================
.PHONY: help install format lint typecheck security schema migrate seed run test check

PYTHON_ENV := PYTHONPATH=src

help: ## نمایش راهنمای دستورات موجود
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## نصب وابستگی‌های قفل‌شده با uv
	uv sync --frozen --all-extras

format: ## قالب‌بندی خودکار کدهای پایتون با Ruff
	uv run ruff format src deploy/cpanel/passenger_wsgi.py
	uv run ruff check --fix src deploy/cpanel/passenger_wsgi.py

lint: ## بررسی قالب‌بندی و قواعد ایستای Ruff
	uv run ruff format --check src deploy/cpanel/passenger_wsgi.py
	uv run ruff check src deploy/cpanel/passenger_wsgi.py

typecheck: ## بررسی سخت‌گیرانهٔ نوع‌ها با Mypy (--strict)
	uv run mypy

security: ## اسکن امنیتی کد (Bandit) و ممیزی آسیب‌پذیری وابستگی‌ها (pip-audit)
	uv run bandit -c pyproject.toml -r src deploy/cpanel/passenger_wsgi.py
	uv run pip-audit

schema: ## تولید و اعتبارسنجی بدون هشدار قرارداد OpenAPI 3.1.0
	DJANGO_SETTINGS_MODULE=config.settings.development $(PYTHON_ENV) uv run python src/manage.py spectacular --api-version v1 --file docs/api/v1/openapi.yaml --validate --fail-on-warn

migrate: ## اعمال مهاجرت‌های MariaDB و ساخت جدول کش اتمیک
	DJANGO_SETTINGS_MODULE=config.settings.development $(PYTHON_ENV) uv run python src/manage.py migrate
	DJANGO_SETTINGS_MODULE=config.settings.development $(PYTHON_ENV) uv run python src/manage.py createcachetable --database=cache

seed: ## بارگذاری داده‌های نمایشی اولیه (خیریه، حرکت، سیاست‌ها و حساب‌های دفتر کل)
	DJANGO_SETTINGS_MODULE=config.settings.development $(PYTHON_ENV) uv run python src/manage.py seed_demo_data

run: ## اجرای سرور توسعه روی پورت ۸۰۰۰
	DJANGO_SETTINGS_MODULE=config.settings.development $(PYTHON_ENV) uv run python src/manage.py runserver 0.0.0.0:8000

test: ## اجرای مجموعه کامل آزمون‌ها روی MariaDB با شرط پوشش شاخه‌ای بالای ۸۵٪
	uv run pytest --cov=apps --cov-branch --cov-report=term-missing --cov-fail-under=85

check: lint typecheck security schema ## اجرای تمامی گیت‌های ایستا، امنیتی و قرارداد API
