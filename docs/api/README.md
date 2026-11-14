# مستندات و حاکمیت قراردادهای API (`docs/api`)

این پوشه مرجع رسمی قراردادهای HTTP سامانه `Crowdfunding-Back` برای تیم‌های فرانت‌اند وب، اپلیکیشن موبایل و ممیزان فنی است.

---

## سیاست نسخه‌گذاری و تکامل بدون شکست (API Versioning & Deprecation)

1. **نسخه‌گذاری صریح در مسیر URL**: کلیهٔ نقاط پایانی کسب‌وکار زیر پیشوند نسخه‌دار `/api/v1/...` قرار دارند.
2. **تکامل سازگار با عقب (Backward-Compatible Evolution)**: افزودن فیلدهای اختیاری جدید به پاسخ‌ها بدون تغییر نسخه انجام می‌شود؛ حذف فیلد یا تغییر معنای فیلد موجود صرفاً در نسخهٔ اصلی بعدی (`/api/v2/...`) مجاز است.
3. **استاندارد منسوخ‌سازی RFC 8594**: هر مسیر در آستانهٔ بازنشستگی هدرهای استاندارد `Deprecation: true`، `Sunset: <HTTP-Date>` و `Link: </api/v2/...>; rel="successor-version"` را ارسال می‌کند (`apps.core.deprecation`).
4. **استاندارد خطای RFC 9457 (`application/problem+json`)**: تمامی خطاهای سامانه بدون استثنا در قالب یکنواخت زیر برگردانده می‌شوند:
   ```json
   {
     "type": "https://github.com/mohebbibrothers/Crowdfunding-Back/blob/main/docs/frontend/ERRORS.md#error-validation_error",
     "title": "خطای اعتبارسنجی داده‌های ورودی",
     "status": 422,
     "detail": "تعداد سهام درخواستی بیش از ظرفیت آزاد حرکت است.",
     "code": "validation_error",
     "instance": "/api/v1/contributions/checkout",
     "trace_id": "019a78f0-1234-7abc-8def-0123456789ab"
   }
   ```

---

## فهرست نسخه‌های فعال

- **[نسخهٔ ۱ (`/api/v1`) — پایدار و فعال](./v1/README.md)**
  🎯 ویژهٔ تحویل به فرانتاند: [`docs/frontend/`](../frontend/README.md) (پورتال، تایپها، کلاینت، خطاها، Postman و چکلیست)
  - فایل طرحوارهٔ کامل OpenAPI 3.1.0: [`docs/api/v1/openapi.yaml`](./v1/openapi.yaml)
  - اعتبارسنجی خودکار بدون هشدار:
    ```bash
    uv run python src/manage.py spectacular --api-version v1 --file docs/api/v1/openapi.yaml --validate --fail-on-warn
    ```
