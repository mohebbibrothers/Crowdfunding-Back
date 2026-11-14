# تأییدیهٔ تحویل بک‌اند به تیم فرانت‌اند

> **نسخه:** `v1.5.0` · **تاریخ:** 2026-11-12 · **کامیت:** _پس از push تکمیل می‌شود_
> **داوری صادقانه:** این سند ادعای «بی‌نقص» نمی‌کند. هرچه واقعاً آماده است با
> شاهد اجراشدنی آمده، و هرچه آماده نیست در بخش «آنچه هنوز نیست» فهرست شده.

---

## ۱. یک نگاه: چه چیزی تحویل می‌شود

| مؤلفه | آمار | وضعیت |
|---|---|---|
| عملیات HTTP | **۱۰۴** در **۸۹ مسیر** | ✅ همه تایپ‌شده |
| اسکیما | **۱۵۲** کامپوننت، **۲۴** enum | ✅ |
| نمونهٔ پاسخ اعتبارسنجی‌شده | **۱۰۳** از ۱۰۳ پاسخ JSON | ✅ تازه در v1.5.0 |
| نمونهٔ بدنهٔ درخواست | **۳۹** | ✅ تازه در v1.5.0 |
| کدهای خطای RFC 9457 | **۳۸** با متن فارسی و راهکار UX | ✅ |
| تست | **۲۲۳ passed** | ✅ |
| پوشش شاخه‌ای | **۸۵.۵۱٪** | ✅ |
| کالکشن Postman | ۱۰۴ درخواست + **۱۰۲ پاسخ ذخیره‌شده** | ✅ تازه در v1.5.0 |

---

## ۲. آنچه در این نسخه تازه شد — و چرا برای شما مهم است

### ۲.۱ نمونهٔ پاسخ برای همهٔ عملیات

**پیش از این:** هر ۱۰۴ عملیات اسکیمای تایپ‌شده داشت ولی **صفر نمونهٔ JSON**.
تیم فرانت باید سه چیز را حدس می‌زد:

| سؤال | حدس اشتباه | پیامد |
|---|---|---|
| تاریخ شمسی است یا ISO؟ | رشتهٔ «۱۴۰۵/۰۸/۲۱» | `new Date()` می‌شکند |
| مبلغ ریال است یا تومان؟ | تومان | **باگ مالی ۱۰ برابری** |
| فیلد خالی `null` است یا حذف می‌شود؟ | حذف | `undefined is not a function` |

**اکنون:** هر پاسخ یک نمونهٔ `realistic` دارد که:

1. **از روی اسکیمای خودش** ساخته شده — نه دست‌نویس.
2. **با `jsonschema` اعتبارسنجی شده** — اگر با اسکیما نخواند، build می‌شکند.
3. **مقادیرش معنادارند** — `amount_rial: 1500000` نه `42`؛ `due_date: "2026-11-12"` نه `"string"`.
4. **خودکار به‌روز می‌شود** — اسکیما که عوض شود، نمونه هم در همان اجرا عوض می‌شود.

```bash
# دیدن نمونهٔ یک پاسخ
make samples        # تزریق نمونه‌ها در قرارداد
make handoff        # بازتولید کل بسته
```

فایل خوانا: [`SAMPLES.md`](./SAMPLES.md) — جدول ۱۰۳ نمونه.

### ۲.۲ enumهای وضعیت — از «هر رشته‌ای» به «این مقادیر»

**پیش از این:** ۱۹ اسکیما فیلد `status` با `{"type": "string"}` داشتند. تایپ
تولیدی TypeScript می‌شد `status: string` و فرانت مجبور بود رشته مقایسه کند:

```typescript
// شکننده: هیچ خطایی نمی‌دهد اگر بک‌اند مقدار را عوض کند
if (payment.status === "verified") { ... }
```

**اکنون:** همه `ChoiceField` با enum واقعی‌اند:

| اسکیما | فیلد | مقادیر |
|---|---|---|
| `PledgeOutput` | `status` | `active` · `paused` · `expired` · `cancelled` · `completed` |
| `PledgeOutput` | `installments_remaining` · `progress_percent` | عدد یا `null` (بی‌پایان) — آمادهٔ نوار پیشرفت |
| `PledgeOutput` | `frequency` | `monthly` · `quarterly` |
| `PledgeInstallmentOutput` | `status` | `scheduled` · `reminded` · `paid` · `failed` · `skipped` · `expired` · `voided` |
| `AdminPayment` | `status` | `initiated` · `verified` · `failed` · `refunded` |
| `CampaignSummary` | `status` | `draft` · `active` · `funded` · `closed` · `cancelled` |
| `CampaignSummary` | `urgency_level` | `normal` · `urgent` · `critical` |
| `DisbursementRequest` | `status` | وضعیت‌های چرخهٔ تسویه |
| `SettlementStatement` | `gateway_name` · `source_kind` · `status` | مجموعه‌های بسته |
| `SettlementRow` | `match_status` | `pending` · `matched` · `duplicate_in_file` · `missing_internal` · `amount_mismatch` · `internal_not_verified` · `missing_gateway` |
| `HealthStatus` | `status` | `healthy` · `degraded` · `unhealthy` |

تایپ TypeScript اکنون union است:

```typescript
type PledgeStatus = "active" | "paused" | "expired" | "cancelled" | "completed";
// IDE هر رشتهٔ اشتباه را قرمز می‌کند، قبل از اجرا.
```

**تضمین پایداری:** تست `test_contract_status_enums_match_model_choices`
دقیقاً می‌سنجد که enum قرارداد با enum مدل یکی باشد. اگر کسی یکی را عوض کند
و دیگری را نه، **CI قرمز می‌شود** — نه در محیط فرانت.

### ۲.۳ کالکشن Postman با پاسخ نمونه

کالکشن را import کنید و **بدون اجرای هیچ درخواستی** شکل واقعی پاسخ هر
عملیات را در تب Examples ببینید. ۱۰۲ از ۱۰۴ درخواست پاسخ ذخیره‌شده دارند
(دو تای باقی `204 No Content` هستند — پاسخ بدنه ندارند).

---

## ۳. هفت قرارداد که باید بدانید

### ۳.۱ احراز هویت سه‌حالته

هر عملیات فیلد `x-frontend-policy.auth` دارد:

| مقدار | معنا | کار شما |
|---|---|---|
| `required` | نیازمند ورود | `Authorization: Bearer` + کوکی نشست |
| `optional` | مهمان هم می‌تواند | اگر توکن دارید بفرستید، وگرنه نه |
| `none` | عمومی | هیچ هدر احراز هویتی نفرستید |

۱۸ عملیات `none` هستند: کاتالوگ عمومی خیریه‌ها، حرکت‌ها، قلک‌ها، callback
درگاه، تأیید رسید، و checkout سریع مهمان.

### ۳.۲ مبالغ: همیشه ریال و تومان، هر دو

**هر فیلد پولی دو نسخه دارد:**

```json
{ "amount_rial": 1500000, "amount_toman": 150000 }
```

- **ریال منبع حقیقت است.** هرگز خودتان تقسیم بر ۱۰ نکنید — فیلد تومانی هست.
- **هیچ `float` در API نیست.** همهٔ مبالغ عدد صحیح ریال‌اند (`BigInteger`).
- در JavaScript از `number` استفاده کنید (تا ۲^۵۳ امن است؛ مبالغ ما میلیاردی‌اند).

### ۳.۳ تاریخ‌ها: سه نمایش، سه کاربرد

| فیلد | نمونه | کاربرد |
|---|---|---|
| `*_at` (ISO 8601) | `"2026-11-12T09:41:00+03:30"` | `new Date()` |
| `jalali` (رشته) | `"۱۷ آبان ۱۴۰۵"` | نمایش مستقیم |
| `*_date` (تاریخ خالص) | `"2026-11-12"` | مقایسهٔ روزانه |

**هرگز تاریخ ISO را با `split("-")` تجزیه نکنید** — منطقهٔ زمانی دارد.
از `new Date(iso)` استفاده کنید.

### ۳.۴ صفحه‌بندی: دو نوع

| نوع | ساختار | کجا |
|---|---|---|
| Cursor | `{ "results": [...], "next_cursor": "..." }` | فهرست‌های بلند (مشارکت‌ها، اعلان‌ها) |
| صفحه‌ای | `{ "results": [...], "meta": { "total": N } }` | پنل ادمین |

`next_cursor: null` یعنی آخر. **کرسر را دستکاری نکنید** — opaque است.

### ۳.۵ خطاها: RFC 9457

همهٔ خطاها `application/problem+json` با این ساختار:

```json
{
  "type": "https://docs.example.com/errors/pledge_amount_too_low",
  "title": "مبلغ تعهد کمتر از حد مجاز است",
  "status": 422,
  "detail": "حداقل مبلغ هر قسط ۵۰٬۰۰۰ ریال است.",
  "code": "pledge_amount_too_low",
  "trace_id": "8f3a..."
}
```

- `code` ماشین‌خوان و پایدار است — **بر اساس آن switch کنید، نه `title`**.
- `trace_id` را در گزارش خطا نگه دارید؛ پشتیبانی با آن پرونده را پیدا می‌کند.
- کاتالوگ کامل ۳۸ کد: [`ERRORS.md`](./ERRORS.md).

### ۳.۶ نوشتن: Idempotency-Key

همهٔ `POST`/`PATCH`/`PUT`/`DELETE` هدر `Idempotency-Key` می‌پذیرند:

```http
Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
```

**برای پرداخت‌ها الزامی است.** اگر شبکه قطع شود و دوباره بفرستید، بدون این
هدر ممکن است دو مشارکت ساخته شود. با آن، پاسخ اول تکرار می‌شود.

### ۳.۷ CSRF: برای نوشتن با کوکی

اگر با کوکی نشست احراز می‌کنید (نه Bearer)، هر نوشتن نیازمند
`X-CSRFToken` از `GET /api/v1/auth/csrf` است. کلاینت ما این را خودکار
ریفرش می‌کند ([`api-client.ts`](./api-client.ts)).

---

## ۴. مسیر پیشنهادی ادغام (۵ گام)

### گام ۱: تولید تایپ‌ها

```bash
# api-types.d.ts از قبل ساخته شده — فقط import کنید
import type { PledgeOutput, PledgeStatus } from "./api-types";
```

### گام ۲: کلاینت

```typescript
import { createClient } from "./api-client";

const api = createClient({
  baseUrl: "https://api.example.ir",
  // onUnauthorized، onCsrfRefresh در کلاینت پیاده شده‌اند
});
```

### گام ۳: اولین صفحه — فهرست تعهدها

```typescript
const pledges: PledgeOutput[] = await api.get("/api/v1/me/pledges");
// pledges[0].status: "active" | "paused" | ... ← autocomplete دارد
```

### گام ۴: پرداخت با Idempotency

```typescript
const result = await api.post(
  `/api/v1/me/pledges/${id}/pay`,
  { installment_id: nextId },
  { idempotencyKey: crypto.randomUUID() },
);
window.location.href = result.redirect_url;
```

### گام ۵: بازگشت از درگاه

درگاه به `payments/callback?Authority=...&Status=OK` برمی‌گردد. شما فقط
نتیجه را نمایش دهید — **تأیید سمت سرور است**، نه سمت شما.

---

## ۵. آنچه هنوز نیست — صادقانه

| موضوع | وضعیت | چرا |
|---|---|---|
| **اپ فرانت‌اند** | ❌ وجود ندارد | این مخزن فقط بک‌اند است. بستهٔ تحویل تایپ‌ها و کلاینت را می‌دهد، نه UI. |
| **درگاه واقعی تست‌شده** | ⚠️ فقط `sandbox` | اعتبارنامهٔ زرین‌پال در دسترس نشد. قرارداد درگاه آماده است (`resolve_payment_gateway`). |
| **پیامک واقعی** | ⚠️ الگوها تعریف‌شده | `SmsPatternCode` باید در پنل اپراتور ثبت شود. |
| **بازپرداخت جزئی** | ❌ نیست | `PaymentRefund.payment` یکتاست (`OneToOne`). در `docs/GAP-ANALYSIS.md` ثبت شده. |
| **تعیین مدت تعهد** | ✅ اکنون هست | `duration_months` (۱ تا ۱۲۰) در بدنهٔ ساخت تعهد؛ خالی = بی‌پایان. پس از آخرین قسط، تعهد خودکار به `completed` می‌رود. |
| **مسیر `me/refunds`** | ❌ نیست | خیر اعلان می‌گیرد ولی نمی‌تواند مستقل وضعیت پولش را بپرسد. |
| **آکادمی/چندزبانه** | ❌ نیست | خارج از دامنهٔ این فاز. |

**هیچ‌کدام از این‌ها مانع شروع کار شما نیست.** همهٔ ۱۰۴ عملیات موجود
کار می‌کنند و تست دارند. این فهرست برای این است که وقتی به آن‌ها رسیدید،
غافلگیر نشوید.

---

## ۶. راستی‌آزمایی خودتان

```bash
# ۱. کل تست‌ها
make test

# ۲. قرارداد بدون هشدار
make schema

# ۳. همگامی بستهٔ فرانت با قرارداد (CI همین را اجرا می‌کند)
make verify-handoff

# ۴. بازسازی نمونه‌ها و دیدنشان
make samples && open docs/frontend/SAMPLES.md
```

باز کردن Swagger UI تعاملی:

```bash
make run
# سپس: http://127.0.0.1:8000/api/docs/
```

هر عملیات اکنون نمونهٔ پاسخ دارد؛ در Swagger روی تب **Example Value** کلیک کنید.

---

## ۷. شماره‌های تماس فنی

| موضوع | فایل |
|---|---|
| قرارداد ماشینی | [`../api/v1/openapi.yaml`](../api/v1/openapi.yaml) |
| تایپ‌های TypeScript | [`api-types.d.ts`](./api-types.d.ts) |
| کلاینت آماده | [`api-client.ts`](./api-client.ts) |
| کاتالوگ خطاها | [`ERRORS.md`](./ERRORS.md) |
| ماتریس عملیات | [`ENDPOINTS.md`](./ENDPOINTS.md) |
| نمونهٔ پاسخ‌ها | [`SAMPLES.md`](./SAMPLES.md) |
| چک‌لیست ادغام | [`CHECKLIST.md`](./CHECKLIST.md) |
| اثر انگشت قرارداد | [`contract-fingerprint.json`](./contract-fingerprint.json) |

اگر قرارداد تغییر کند، اثر انگشت عوض می‌شود و `make verify-handoff` قرمز
می‌شود — یعنی **هرگز نسخهٔ قدیمی را نمی‌بینید**.
