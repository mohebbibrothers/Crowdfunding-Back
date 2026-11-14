/**
 * 🧪 «تست تایپ» (Compile-Time Contract Test)
 *
 * این فایل هیچ کدی اجرا نمیکند؛ فقط اثبات میکند که `api-client.ts`،
 * `operations.ts` و `api-types.d.ts` در کنار هم با `strict: true` کامپایل میشوند
 * و تایپ پاسخ/درخواست از روی `operationId` بهدرستی استنتاج میگردد.
 *
 * اجرا: `npx tsc --noEmit -p docs/frontend/tsconfig.json`
 */

import { ApiClientError, createApiClient } from "./api-client";
import type { ApiOperation, CampaignSummary, ProblemCode } from "./api-types";

const client = createApiClient({
  baseUrl: "https://api.charity.example.org",
  authMode: "cookie",
  onSessionExpired: () => undefined,
  onStepUpRequired: () => undefined,
});

async function integrationSmoke(): Promise<void> {
  // ۱) عملیات بدون گزینه: opts اختیاری است و پاسخ تایپشده برمیگردد.
  const meta = await client.request("v1_meta_retrieve");
  const holdMinutes: number = meta.share_hold_ttl_minutes;
  void holdMinutes;

  // ۲) فهرست عمومی + query.
  //    ⚠️ خروجی **پوشه** است، نه آرایه: { ordering, count, results }.
  //    اگر روزی به آرایه برگردد، همین دو خط خطا می‌دهند و ما می‌فهمیم —
  //    دقیقاً همان کاری که این فایل باید بکند.
  const campaignList: ApiOperation<"v1_campaigns_list">["response"] = await client.request(
    "v1_campaigns_list",
    { query: { order: "fair", status: "active" } },
  );
  const campaigns: Array<CampaignSummary> = campaignList.results;
  const appliedOrdering: string = campaignList.ordering;
  void campaigns.length;
  void appliedOrdering;

  // ۳) بدنهٔ نوشتنی دقیقاً با اسکیمای CheckoutInitiateInputRequest چک میشود.
  const checkout = await client.request("v1_contributions_checkout_create", {
    body: {
      target_kind: "campaign_shares",
      campaign_id: "01936f00-0000-7000-8000-000000000000",
      shares_count: 3,
      gateway_name: "sandbox",
    },
  });
  const redirect: string = checkout.gateway_redirect_url;
  const amountToman: number = checkout.amount_toman;
  void redirect;
  void amountToman;

  // ۴) پوشش صفحهبندی `{results, meta}` و meta.nextnullable.
  const page = await client.request("v1_me_contributions_list", { query: { page_size: 20 } });
  const next: string | null = page.meta.next;
  void next;

  // ۵) پیمایش مکاننمایی بدون ساخت دستی cursor.
  for await (const cursorPage of client.paginate("v1_me_contributions_list")) {
    void cursorPage.results.length;
    break;
  }

  // ۶) تاریخ‌ها رشتهٔ ISO-8601‌اند (نه epoch) و گزارش اکسل Blob برمی‌گرداند.
  const profile: ApiOperation<"v1_me_profile_retrieve">["response"] =
    await client.request("v1_me_profile_retrieve");
  const createdAt: string = profile.created_at;
  const createdJalali: string | null = profile.created_at_jalali;
  void new Date(createdAt);
  void createdJalali;

  const workbook: Blob = await client.request("v1_admin_reports_excel_export");
  void workbook.size;

  // ۷) خطای RFC 9457 بهصورت تایپشده و با کد ماشینی پایدار قابل branching است.
  try {
    await client.request("v1_auth_otp_request", { body: { phone: "09121112233" } });
  } catch (error: unknown) {
    if (error instanceof ApiClientError) {
      const code: ProblemCode = error.code as ProblemCode;
      const trace: string = error.traceId;
      void code;
      void trace;
      void error.needsStepUp;
      void error.isCsrfExpired;
      void error.isSessionExpired;
    }
  }
}

void integrationSmoke;
