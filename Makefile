# ==============================================================================
# Crowdfunding-Back — میانبرهای توسعه، کنترل کیفیت، طرحواره و اجرای محلی
# ==============================================================================
.PHONY: help install format lint typecheck tscheck security schema handoff verify-handoff migrate seed run test check

PYTHON_ENV := PYTHONPATH=src

help: ## نمایش راهنمای دستورات موجود
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## نصب وابستگی‌های قفل‌شده با uv
	uv sync --frozen --all-extras

format: ## قالب‌بندی خودکار کدهای پایتون با Ruff
	uv run ruff format src scripts deploy/cpanel/passenger_wsgi.py
	uv run ruff check --fix src scripts deploy/cpanel/passenger_wsgi.py

lint: ## بررسی قالب‌بندی و قواعد ایستای Ruff
	uv run ruff format --check src scripts deploy/cpanel/passenger_wsgi.py
	uv run ruff check src scripts deploy/cpanel/passenger_wsgi.py

typecheck: ## بررسی سخت‌گیرانهٔ نوع‌ها با Mypy (--strict)
	uv run mypy

tscheck: ## بررسی تایپهای TypeScript بستهٔ فرانتاند (نیازمند Node.js 20+)
	npx --yes --package typescript@5.9.3 tsc --noEmit -p docs/frontend/tsconfig.json

security: ## اسکن امنیتی کد (Bandit) و ممیزی آسیب‌پذیری وابستگی‌ها (pip-audit)
	uv run bandit -c pyproject.toml -r src deploy/cpanel/passenger_wsgi.py
	uv run pip-audit

schema: ## تولید و اعتبارسنجی بدون هشدار قرارداد OpenAPI 3.1.0
	DJANGO_SETTINGS_MODULE=config.settings.development $(PYTHON_ENV) uv run python src/manage.py spectacular --api-version v1 --file docs/api/v1/openapi.yaml --validate --fail-on-warn

handoff: schema ## بازتولید بستهٔ کامل تحویل فرانتاند از روی قرارداد OpenAPI
	$(PYTHON_ENV) uv run python scripts/build_frontend_kit.py

verify-handoff: ## راستیآزمایی همگامی بستهٔ فرانتاند با قرارداد (بدون ایجاد تغییر)
	@$(PYTHON_ENV) uv run python scripts/build_frontend_kit.py >/dev/null
	@git diff --exit-code -- docs/frontend docs/api/v1/openapi.yaml \
		|| (echo "❌ بستهٔ فرانتاند با قرارداد همگام نیست: make handoff را اجرا و commit کنید."; exit 1)
	@echo "✅ قرارداد و بستهٔ فرانتاند کاملاً همگام هستند."

migrate: ## اعمال مهاجرت‌های MariaDB و ساخت جدول کش اتمیک
	DJANGO_SETTINGS_MODULE=config.settings.development $(PYTHON_ENV) uv run python src/manage.py migrate
	DJANGO_SETTINGS_MODULE=config.settings.development $(PYTHON_ENV) uv run python src/manage.py createcachetable --database=cache

seed: ## بارگذاری داده‌های نمایشی اولیه (خیریه، حرکت، سیاست‌ها و حساب‌های دفتر کل)
	DJANGO_SETTINGS_MODULE=config.settings.development $(PYTHON_ENV) uv run python src/manage.py seed_demo_data

run: ## اجرای سرور توسعه روی پورت ۸۰۰۰
	DJANGO_SETTINGS_MODULE=config.settings.development $(PYTHON_ENV) uv run python src/manage.py runserver 0.0.0.0:8000

test: ## اجرای مجموعه کامل آزمون‌ها روی MariaDB با شرط پوشش شاخه‌ای بالای ۸۵٪
	uv run pytest --cov=apps --cov-branch --cov-report=term-missing --cov-fail-under=85

check: lint typecheck tscheck security schema verify-handoff ## اجرای تمامی گیتهای ایستا، امنیتی، قرارداد API، تایپهای TS و بستهٔ فرانتاند
