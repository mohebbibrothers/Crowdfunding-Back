# 👋 تیم فرانت‌اند — از اینجا شروع کنید

> **نسخه:** `v1.2.0` · **وضعیت بک‌اند:** پایدار و قفل‌شده با CI · **آخرین گیت:** ۱۹/۱۹ سبز
> **آمادگی شروع کار:** ۹۶/۱۰۰ · **نقص مسدودکننده:** صفر

این فایل فقط یک کار دارد: شما را در **کمتر از ۵ دقیقه** به نقطهٔ کدنویسی برساند.

---

## ۱. سه لینک که کافی است

| اولویت | لینک | چه چیزی می‌دهد |
| --- | --- | --- |
| ۱ | **[`docs/frontend/index.html`](docs/frontend/index.html)** | پورتال بصری آفلاین: کاوشگر ۱۰۴ عملیات، آمار زنده، همه‌چیز در یک صفحه |
| ۲ | **[`docs/frontend/HANDOFF.md`](docs/frontend/HANDOFF.md)** | راهنمای جامع: قراردادها، جریان OTP، CSRF، Step-Up، پرداخت، صفحه‌بندی، پول و تقویم |
| ۳ | **[`docs/frontend/DELIVERY.md`](docs/frontend/DELIVERY.md)** | تأییدیهٔ تحویل بک‌اند: آمار واقعی، هفت قرارداد، مسیر ادغام ۵ گامی، فهرست صادقانهٔ کمبودها |
| ۳ | **[`docs/frontend/ACCEPTANCE.md`](docs/frontend/ACCEPTANCE.md)** | تأییدیهٔ نهایی: چه چیزی تحویل شده، چه چیزی رفع شده، چه چیزی مانده |

> 📖 اگر فقط یک فایل می‌خوانید، `HANDOFF.md` را بخوانید (۳۷۹ خط، ۱۵ دقیقه).
> اگر می‌خواهید بدانید «چقدر قابل‌اعتماد است»، `READINESS-AUDIT.md` را بخوانید.

---

## ۲. کاری که همین حالا باید بکنید

### الف) ساده‌ترین راه — Docker (بدون نصب MariaDB)

```bash
git clone https://github.com/mohebbibrothers/Crowdfunding-Back.git
cd Crowdfunding-Back
docker compose up --build -d                  # MariaDB 11.4 + Web + Cron
docker compose exec web python src/manage.py seed_demo_data   # داده‌های نمایشی
```

### ب) اگر MariaDB را محلی دارید (`uv` + `make`)

```bash
git clone https://github.com/mohebbibrothers/Crowdfunding-Back.git
cd Crowdfunding-Back
make install      # نصب وابستگی‌های قفل‌شده با uv

# ⚠️ این خط را جا نیندازید (پیش‌فرض همان مقدار زیر است، ولی صریح بهتر است)
export DATABASE_URL="mysql://crowdfunding:crowdfunding@127.0.0.1:3306/crowdfunding"

make migrate      # ساخت جداول + جدول کش اتمیک
make seed         # داده‌های نمایشی: خیریه، حرکت، قلک، دفتر کل
make run          # http://localhost:8000
```

### در هر دو حالت، این‌ها را ببینید

| چه چیزی | آدرس |
| --- | --- |
| Swagger UI | `http://localhost:8000/api/v1/docs` |
| ReDoc | `http://localhost:8000/api/v1/redoc` |
| اسکیما (JSON/YAML) | `http://localhost:8000/api/v1/schema` |
| آمادگی سرویس | `http://localhost:8000/api/v1/health/ready` |

### بعد: بستهٔ فرانت را بردارید

```bash
cp -r docs/frontend ../my-frontend/src/api   # کل بسته، یک‌جا

# تایپ‌ها را چک کنید — باید «صفر خطا» بدهد (نیازمند Node.js ۲۰+)
make tscheck
```

> 💡 در محیط توسعه `EXPOSE_DEV_OTP_CODE=true` است؛ کد OTP در پاسخ
> `POST /api/v1/auth/otp/request` برمی‌گردد. درگاه پیش‌فرض `sandbox` است.

---

## ۳. کد شروع — همین را کپی کنید

```ts
import { createApiClient, ApiClientError } from "./src/api/api-client";

const client = createApiClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL,   // https://api.charity.example.org
  authMode: "cookie",                           // یا "bearer" برای موبایل
  onSessionExpired: () => router.push("/login"),
  onStepUpRequired: () => openTotpModal(),
});

// ۱) بوت: پرچم‌های ویژگی و تاریخ امروز (همه‌چیز تایپ‌شده است)
const meta = await client.request("v1_meta_retrieve");
if (!meta.features.merkle_transparency) hideMerkleWidget();
console.log("backend", meta.app_version, "today", meta.today_jalali);

// ۲) فهرست حرکات — پوشش { ordering, count, results }
const campaignList = await client.request("v1_campaigns_list", {
  query: { order: "fair", status: "active" },
});
const [first] = campaignList.results;
if (!first) throw new Error("هیچ حرکتی برای نمایش نیست");

// ۳) پرداخت: انتخاب سهم ⇒ رزرو ۱۵ دقیقه‌ای ⇒ هدایت به درگاه
const checkout = await client.request("v1_contributions_checkout_create", {
  body: {
    target_kind: "campaign_shares",
    campaign_id: first.id,
    shares_count: 3,
    gateway_name: "sandbox",
  },
  idempotencyKey: crypto.randomUUID(),   // ⚠️ ثابت نگه دارید تا پایان همان تلاش
});
window.location.href = checkout.gateway_redirect_url;
```

**نکتهٔ تایپ:** سه شکل پاسخ فهرستی داریم و `tsc` هر اشتباهی را می‌گیرد:

| شکل | نمونه | چطور بشناسید |
|---|---|---|
| آرایهٔ ساده | `v1_campaign_categories_list` | پاسخ بدون پوشش |
| `{ ordering, count, results }` | `v1_campaigns_list` | `.results` |
| `{ results, meta }` | `v1_me_contributions_list` و بقیهٔ صفحه‌بندی‌شده‌ها | `.results` + `.meta.next` |

اگر شکل را اشتباه بگیرید — مثلاً `campaigns.map` روی پوشه — `tsc` قبل از اجرا
خطا می‌دهد. این عمدی است: قرارداد در v1.5.0 دقیقاً مطابق رفتار واقعی سرور
اصلاح شد و همین تست، واگرایی را گرفت.

**قاعدهٔ طلایی:** هیچ `fetch` خام ننویسید، هیچ مسیری را hardcode نکنید، هیچ خطایی را با
`detail` مقایسه نکنید. همه‌چیز از `client.request(operationId, ...)` و `error.code` بیاید.

---

## ۴. ده قراردادی که اگر رعایت نکنید باگ می‌گیرید

| # | قرارداد | اشتباه رایج |
| --- | --- | --- |
| ۱ | تاریخ‌ها **ISO-8601 با انحراف زمانی** (`+03:30`) هستند | `new Date(Number(x))` ⇒ نمایش ۱۹۷۰ |
| ۲ | `*_toman` را نمایش بدهید؛ خودتان تقسیم بر ۱۰ نکنید | خطای گرد کردن |
| ۳ | نمایش تاریخ از `*_jalali` که **با خط تیره** است (`1405-08-23`) | تبدیل تقویم سمت کلاینت |
| ۴ | خطاها را با `error.code` بشناسید، نه `detail` | مقایسهٔ متن فارسی ⇒ شکستن با هر تغییر کپی |
| ۵ | `csrf_failed` را **به کاربر نشان ندهید**؛ کلاینت خودش بازیابی می‌کند | نمایش «شما دسترسی ندارید» به کاربری که دسترسی دارد |
| ۶ | `403 step_up_required` ⇒ مودال TOTP ⇒ **همان** `Idempotency-Key` | ساخت کلید تازه ⇒ پرداخت تکراری |
| ۷ | صفحه‌بندی: `meta.next` را عیناً استفاده کنید | ساخت دستی `cursor` |
| ۸ | `meta.total` فقط در فهرست‌های شخصی هست (۵ لیست ادمین ندارند) | نمایش «۱ از ۰» |
| ۹ | گزارش اکسل `Blob` است: `client.download()` + `client.saveBlob()` | `JSON.parse` روی xlsx |
| ۱۰ | `200/201` با `X-Idempotent-Replayed: true` یعنی بازپخش | نمایش «ثبت شد» برای بار دوم |

---

## ۵. چه چیزی تایپ‌شده است

| سنجه | مقدار |
| --- | --- |
| عملیات با پاسخ تایپ‌شده | **۸۳ از ۸۳** (۰ مورد `any` یا `unknown`) |
| اسکیما | ۱۱۲ |
| کد خطای ماشینی | ۳۸ (همه با شرح فارسی و اقدام UX) |
| نمونهٔ بدنهٔ درخواست | ۸ |
| درخواست Postman | ۸۳ در ۲۳ پوشه (import مستقیم) |
| عملیات عمومی | ۱۸ با `security: []` صریح |
| عملیات اجباری / اختیاری | ۵۷ / ۸ |

---

## ۶. بازیابی از خطاهای رایج

| خطا | معنا | کار درست |
| --- | --- | --- |
| `401 authentication_required` | نشست منقضی | `onSessionExpired` ⇒ صفحهٔ ورود |
| `403 csrf_failed` | توکن CSRF کهنه | کلاینت خودکار جبران می‌کند؛ **نشان ندهید** |
| `403 mfa_required` | کارمند باید TOTP بزند | مودال TOTP |
| `403 step_up_required` | عملیات حساس، TOTP تازه | مودال و بازارسای با **همان** کلید |
| `404 invalid_cursor` | cursor کهنه | پاک‌سازی کش و شروع بدون cursor |
| `409 idempotency_conflict` | همان کلید با بدنهٔ دیگر | `Idempotency-Key` تازه |
| `410 resource_expired` | رزرو ۱۵ دقیقه‌ای سهم گذشت | بازگشت به انتخاب سهم |
| `422 validation_error` | خطای فیلد | `error.fieldErrors[field]` زیر همان فیلد |
| `429 / 503` | سقف نرخ / اضافه‌بار | `Retry-After`؛ کلاینت خودکار backoff می‌کند |
| `500 internal_error` | خطای سرور | فقط `trace_id` را به پشتیبانی بدهید |

---

## ۷. اگر به مشکل خوردید

1. اول [`HANDOFF.md` بخش ۸ «عیب‌یابی سریع»](docs/frontend/HANDOFF.md) را ببینید.
2. بعد [`ERRORS.md`](docs/frontend/ERRORS.md) — برای هر ۳۸ کد، شرح و اقدام UX هست.
3. اگر باز هم مبهم بود، `trace_id` را بردارید و به تیم بک‌اند بدهید.

> **قرارداد عملاً قفل است:** هر تغییری در بک‌اند بدون بازتولید بستهٔ فرانت، CI را قرمز می‌کند.
> یعنی چیزی که امروز می‌سازید تا زمانی که `v1` است، ناگهان شکل عوض نمی‌کند.
