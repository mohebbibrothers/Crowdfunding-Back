# راهنمای مشارکت و توسعه (`Contributing Guide`)

از همراهی شما در توسعه و ارتقای **`Crowdfunding-Back`** سپاسگزاریم. برای حفظ یکپارچگی مالی، امنیت و تمیزی معماری، رعایت قواعد زیر در تمامی Pull Requestها الزامی است.

---

## ۱. قواعد آهنین معماری (غیرقابل‌مذاکره)

1. **حفظ گراف غیرمدور ۹ ماژول (Acyclic 9-App DAG)**:
   ترتیب مجاز وابستگی همواره یک‌طرفه است:
   `core -> audit -> identity -> notifications -> benefactors -> campaigns -> ledger -> contributions -> reporting`
   هرگونه نیاز به ارتباط معکوس باید صرفاً از طریق **پورت‌های زمان اجرا (Hexagonal Ports)** پیاده‌سازی شود؛ تست `test_bounded_context_acyclic_dag_discipline` در CI این قانون را بررسی می‌کند.
2. **لایهٔ View لاغر (Thin Views)**:
   کلاس‌های View در هیچ ماژولی مجاز به فراخوانی مستقیم `.save()`، `.create()`، `.update()` یا `.delete()` روی مدل‌ها نیستند. تمامی تغییرات وضعیت باید درون توابع تراکنشی `services.py` انجام شوند (`test_thin_views_never_mutate_models_directly`).
3. **ممنوعیت مطلق `float` برای پول**:
   تمامی مبالغ در دیتابیس و دفتر کل باید عدد صحیح ریال (`int` / `BIGINT`) باشند و در خروجی‌های API به کمک `rial_to_toman` هر دو فیلد `*_rial` و `*_toman` بازگردانده شوند.
4. **به‌روزرسانی قرارداد OpenAPI 3.1**:
   پس از هر تغییر در سریالایزرها یا مسیرهای API، طرحواره را بازتولید و بدون هشدار اعتبارسنجی کنید:
   ```bash
   make handoff   # بازتولید طرحواره + تایپها/کالکشن/مستندات فرانتاند
   ```
   ⚠️ فایلهای `docs/frontend/` با علامت 🟢 **تولیدشدهٔ خودکار** هستند؛ هرگز دستکاری نشوند.
   گیت `make verify-handoff` و CI هرگونه درفت بین قرارداد و بستهٔ فرانتاند را رد میکنند.
   خطاهای تازه حتماً در `PROBLEM_CODES` (`apps/core/schema.py`) ثبت شوند تا همزمان در
   OpenAPI و `ERRORS.md` منعکس گردند.

---

## ۲. گیت‌های الزامی پیش از ارسال Pull Request

پیش از ثبت هر کامیت یا PR، دستور یکپارچهٔ زیر را اجرا کنید تا از سبز بودن تمامی بررسی‌ها اطمینان حاصل شود:

```bash
make check
make test
```

این دستورات به ترتیب موارد زیر را اجرا می‌کنند:
- `uv run ruff format --check src scripts` و `uv run ruff check src scripts`
- `uv run mypy` (حالت `--strict`)
- `make tscheck` (بررسی تایپهای TypeScript بستهٔ فرانتاند با `strict: true`)
- `uv run bandit -c pyproject.toml -r src`
- `uv run pip-audit`
- `manage.py makemigrations --check --dry-run`
- `manage.py spectacular --validate --fail-on-warn`
- `make handoff` و گیت همگامی بستهٔ فرانتاند (`git diff --exit-code`)
- `uv run pytest --cov=apps --cov-branch --cov-fail-under=85`

---

## ۳. استاندارد پیام‌های کامیت (Conventional Commits)

پیام‌های کامیت باید ساختاریافته و گویا باشند:
- `feat(campaigns): ...` — افزودن قابلیت جدید
- `fix(ledger): ...` — رفع خطای منطقی یا امنیتی
- `docs(api): ...` — بهبود مستندات یا طرحوارهٔ OpenAPI
- `test(contributions): ...` — افزودن یا تکمیل آزمون‌ها
- `chore(ci): ...` — بهبود ابزارهای ساخت، وابستگی‌ها یا CI
