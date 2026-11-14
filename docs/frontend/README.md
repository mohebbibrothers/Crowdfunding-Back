# 🎯 بستهٔ تحویل فرانتاند (Frontend Handoff Kit)

> **نسخهٔ نهایی:** `v1.1.0` · **منبع حقیقت:** [`../api/v1/openapi.yaml`](../api/v1/openapi.yaml) · **وضعیت:** قفلشده با CI

از همینجا شروع کنید 👇

| میخواهم… | بروم به |
| --- | --- |
| **تازه آمده‌ام، از کجا شروع کنم؟** | [`../../START-HERE.md`](../../START-HERE.md) — راهنمای ورود ۵ دقیقه‌ای با کد آماده |
| **همهچیز را یکجا و بصری ببینم** | [`index.html`](./index.html) — پورتال آفلاین با کاوشگر ۸۳ عملیات |
| **شروع به کدنویسی کنم** | [`HANDOFF.md`](./HANDOFF.md) — راهنمای جامع، قراردادها، جریانها و نمودارها |
| **تایپها را import کنم** | [`api-types.d.ts`](./api-types.d.ts) + [`operations.ts`](./operations.ts) |
| **کلاینت HTTP آماده بردارم** | [`api-client.ts`](./api-client.ts) — بدون وابستگی خارجی |
| **فهرست دقیق متد/مسیر را ببینم** | [`ENDPOINTS.md`](./ENDPOINTS.md) |
| **خطاها را هندل کنم** | [`ERRORS.md`](./ERRORS.md) — ۳۸ کد RFC 9457 + اقدام UX |
| **سریعاً در Postman تست کنم** | [`postman_collection.json`](./postman_collection.json) |
| **پیش از استقرار چک کنم** | [`CHECKLIST.md`](./CHECKLIST.md) |
| **تأییدیهٔ نهایی برای مدیر/کارفرما** | [`ACCEPTANCE.md`](./ACCEPTANCE.md) — یک صفحه، آمادهٔ ارائه |
| **بدانم چه چیزی ممیزی و رفع شده** | [`READINESS-AUDIT.md`](./READINESS-AUDIT.md) — گزارش ممیزی مستقل با ۳ نقص مسدودکنندهٔ اثبات‌شده |

---

## فلسفهٔ این بسته: «قرارداد، یکبار؛ everywhere»

```
        apps/*/views.py + serializers.py
                  │  drf-spectacular + apps/core/schema.py (Contract Enrichment)
                  ▼
        docs/api/v1/openapi.yaml  ← منبع حقیقت واحد (CI آن را قفل میکند)
                  │  scripts/build_frontend_kit.py
     ┌────────────┼────────────┬──────────────┬─────────────┐
     ▼            ▼            ▼              ▼             ▼
api-types.d.ts  operations.ts  ENDPOINTS.md  ERRORS.md   postman_collection.json
     └────────────┴────── api-client.ts ─┴── index.html ─────┘
```

هیچ مسیر، متد، فیلد یا کد خطایی دوبار دستنویس نشده است. CI در هر push:

1. قرارداد را از کد تولید میکند و `diff` صفر میگیرد،
2. آن را با `--validate --fail-on-warn` اعتبارسنجی میکند،
3. بستهٔ فرانتاند را بازتولید کرده و **هرگونه تغییر commitنشده را رد میکند**،
4. گیتهای انضباط مستندات (همخوانی README، خطاها، صفحهبندی، تایپها) را اجرا مینماید.

نتیجه: **اگر بکاند تغییر کند و فرانتاند بیتوجه بماند، build قرمز میشود.**

---

## شروع سریع

```bash
# بکاند محلی
make install && make migrate && make seed && make run
# کاوش: http://localhost:8000/api/v1/docs  |  /api/v1/redoc

# داراییهای فرانتاند (پس از هر تغییر قرارداد)
make handoff
make tscheck     # بررسی تایپها با TypeScript 5.9 strict

# کپی در پروژهٔ فرانتاند
cp -r docs/frontend ../my-app/src/api
```

```ts
import { createApiClient } from "./src/api/api-client";

const client = createApiClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL,   // https://api.charity.example.org
  authMode: "cookie",                            // یا "bearer" برای موبایل
  onSessionExpired: () => router.push("/login"),
  onStepUpRequired: () => openTotpModal(),
});

// تایپ پاسخ بهصورت خودکار از operationId استنتاج میشود
const campaigns = await client.request("v1_campaigns_list", {
  query: { order: "fair", status: "active" },
});

const checkout = await client.request("v1_contributions_checkout_create", {
  body: { target_kind: "campaign_shares", campaign_id: "<uuid>", shares_count: 3, gateway_name: "sandbox" },
});
window.location.href = checkout.gateway_redirect_url;
```

---

## فهرست کامل فایلها

| فایل | اندازهٔ منطقی | تولید | توضیح |
| --- | --- | --- | --- |
| `index.html` | پورتال تعاملی RTL | دستنویس + تزریق داده | کاملاً آفلاین؛ بدون CDN/فونت خارجی |
| `HANDOFF.md` | راهنمای جامع | دستنویس | ۹ بخش + نمودارهای Mermaid |
| `CHECKLIST.md` | چکلیست پذیرش | دستنویس | Definition of Done |
| `api-client.ts` | کلاینت fetch | دستنویس | CSRF/JWT/refresh/خطا/retry/ETag/pagination |
| `api-types.d.ts` | ۱۱۲ اسکیما + `ApiOperationMap` | 🟢 خودکار | عدم دستکاری |
| `operations.ts` | ۸۳ نگاشت operationId | 🟢 خودکار | عدم دستکاری |
| `ENDPOINTS.md` | ماتریس متد/مسیر/پارامتر | 🟢 خودکار | عدم دستکاری |
| `ERRORS.md` | ۳۸ کد خطا + لنگر `type` | 🟢 خودکار | عدم دستکاری |
| `postman_collection.json` | ۲۳ پوشه / ۸۳ درخواست | 🟢 خودکار | عدم دستکاری |
| `contract-fingerprint.json` | SHA-256 قرارداد | 🟢 خودکار | مبنای گیت CI |
| `README.md` | نقشهٔ ورودی بسته | دستنویس | شروع سریع |
| `tsconfig.json` + `type-tests.ts` | `strict` TypeScript | دستنویس | `make tscheck` |

---

## سؤالهای پرتکرار

**قرارداد کجاست؟** `docs/api/v1/openapi.yaml` و تعاملی روی `/api/v1/docs` و `/api/v1/redoc`.

**آرایه میگیرم یا `{results, meta}`؟** پنج لیست مکاننمایی پوشش میگیرند (در HANDOFF §۲٫۴ آمده)؛
بقیه آرایهٔ مستقیماند. قرارداد برای هرکدام دقیقاً مشخص کرده است.

**چطور بفهمم قابلیتی فعال است؟** `GET /api/v1/meta` ← `features`. فقط همان مبناست.

**نسخهٔ بکاند مستقرشده چیست؟** `GET /api/v1/meta` ← `app_version` (مثلاً `1.1.0`).

**کد OTP در توسعه چطور بهدست بیاید؟** `EXPOSE_DEV_OTP_CODE=true` است؛ کد در پاسخ `otp/request` برمیگردد.

**درگاه پرداخت واقعی لازم است؟** خیر؛ `PAYMENT_DEFAULT_GATEWAY=sandbox` یک شبیهساز تعاملی میدهد
(`GET /api/v1/payments/sandbox/{authority}`).

**ریال بفرستم یا تومان؟** فقط **ریال صحیح**؛ نمایش همیشه از فیلد `*_toman` آمادهٔ سرور.
