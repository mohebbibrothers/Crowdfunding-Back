# راهنمای گام‌به‌گام استقرار روی هاست سی‌پنل نایترو (Nitro cPanel + CloudLinux Passenger)

این سرویس به‌صورت بومی و بدون وابستگی اجباری به Redis یا Celery برای اجرا روی محیط‌های استاندارد **CloudLinux Python Selector (Phusion Passenger)** و **MariaDB / MySQL** طراحی شده است.

---

## ۱. ساخت دیتابیس در سی‌پنل (`MySQL® Database Wizard`)

1. وارد پنل سی‌پنل شوید و از بخش **Databases** گزینهٔ **MySQL® Database Wizard** را باز کنید.
2. یک دیتابیس جدید (مثلاً `cpaneluser_cfdb`) و یک کاربر اختصاصی (مثلاً `cpaneluser_cfapp`) با رمز عبور قوی بسازید.
3. تیک **ALL PRIVILEGES** را روی همان دیتابیس فعال کنید.
4. اطمینان حاصل کنید که Collation دیتابیس روی `utf8mb4_unicode_ci` یا `utf8mb4_uca1400_as_cs` قرار دارد.

---

## ۲. راه‌اندازی برنامه پایتون (`Setup Python App`)

1. از بخش **Software** وارد **Setup Python App** شوید و روی **Create Application** کلیک کنید:
   - **Python version**: `3.12` (پیشنهادی؛ با `3.11+` نیز کاملاً سازگار است)
   - **Application mode**: `Production`
   - **Application root**: `Crowdfunding-Back`
   - **Application URL**: دامنه یا زیردامنهٔ API (مثلاً `api.yourdomain.ir`)
   - **Application startup file**: `deploy/cpanel/passenger_wsgi.py`
   - **Application Entry point**: `application`
2. پس از ایجاد برنامه، دستور فعال‌سازی محیط مجازی (بالای صفحه نمایش داده می‌شود) را کپی و در **Terminal** سی‌پنل اجرا کنید:
   ```bash
   source /home/CPANEL_USER/virtualenv/Crowdfunding-Back/3.12/bin/activate
   cd /home/CPANEL_USER/Crowdfunding-Back
   ```

> **نکتهٔ مهم درایور دیتابیس**: اگر روی سرور اشتراکی کتابخانهٔ سیستمی `libmariadbclient-dev` نصب نباشد و نصب `mysqlclient` خطا بدهد، فایل `passenger_wsgi.py` به‌طور خودکار از درایور خالص پایتونی `PyMySQL` (که در وابستگی‌های پروژه تعبیه شده است) استفاده می‌کند.

---

## ۳. تنظیم متغیرهای محیطی (`.env`) و اجرای اسکریپت استقرار

1. فایل `.env` را از روی `.env.example` بسازید و مجوز دسترسی آن را محدود کنید:
   ```bash
   cp .env.example .env
   chmod 600 .env
   ```
2. کلیدهای مستقل امنیتی را با پایتون تولید و در `.env` قرار دهید:
   ```bash
   python -c "import secrets; print('DJANGO_SECRET_KEY=' + secrets.token_urlsafe(50))"
   python -c "import secrets; print('FIELD_ENCRYPTION_KEY=' + secrets.token_urlsafe(32))"
   python -c "import secrets; print('PII_BLIND_INDEX_KEY=' + secrets.token_urlsafe(32))"
   python -c "import secrets; print('AUDIT_ANCHOR_HMAC_KEY=' + secrets.token_urlsafe(32))"
   ```
3. اسکریپت استقرار خودکار را اجرا کنید:
   ```bash
   chmod +x deploy/cpanel/deploy.sh deploy/cpanel/cron_jobs.sh
   ./deploy/cpanel/deploy.sh
   ```

---

## ۴. تنظیم زمان‌بندهای پس‌زمینه (`Cron Jobs` سی‌پنل)

از بخش **Advanced -> Cron Jobs** در سی‌پنل، سه ردیف زیر را (با جایگزینی `CPANEL_USER` و مسیر دقیق محیط مجازی) ثبت کنید:

```cron
# ۱. پردازش صف تراکنشی پیامک و اعلان‌ها (هر دقیقه)
* * * * * VIRTUAL_ENV=/home/CPANEL_USER/virtualenv/Crowdfunding-Back/3.12 /home/CPANEL_USER/Crowdfunding-Back/deploy/cpanel/cron_jobs.sh outbox >> /home/CPANEL_USER/logs/cf-cron.log 2>&1

# ۲. آزادسازی سهم‌های رزرو منقضی‌شده ۱۵ دقیقه‌ای و پاک‌سازی نشست‌ها (هر ۲ دقیقه)
*/2 * * * * VIRTUAL_ENV=/home/CPANEL_USER/virtualenv/Crowdfunding-Back/3.12 /home/CPANEL_USER/Crowdfunding-Back/deploy/cpanel/cron_jobs.sh reap >> /home/CPANEL_USER/logs/cf-cron.log 2>&1

# ۳. امضای دوره‌ای لنگر زنجیره ممیزی و عکس کنترل تراز دفتر کل (هر ساعت)
0 * * * * VIRTUAL_ENV=/home/CPANEL_USER/virtualenv/Crowdfunding-Back/3.12 /home/CPANEL_USER/Crowdfunding-Back/deploy/cpanel/cron_jobs.sh anchor >> /home/CPANEL_USER/logs/cf-cron.log 2>&1
```

---

## ۵. فعال‌سازی پنل پیامک در آینده (بدون تغییر کد)

تا پیش از دریافت کلید پنل پیامک از سوی کارفرما، متغیر `SMS_ENABLED=false` باقی می‌ماند و کلیه رویدادها در جدول `notifications_sms_delivery_log` با وضعیت `mocked` ثبت می‌شوند. به محض تحویل پنل پیامک (کاوه‌نگار، ملی‌پیامک، مدیانا یا فراز اس‌ام‌اس):
1. در فایل `.env` مقادیر `SMS_ENABLED=true`، `SMS_API_URL`، `SMS_API_KEY` و `SMS_PATTERN_CODES_JSON` را وارد کنید.
2. دستور `touch tmp/restart.txt` را اجرا نمایید تا Passenger بدون قطعی سرویس بازخوانی شود.
