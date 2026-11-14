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
import type { ApiOperation, ProblemCode } from "./api-types";

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

  // ۲) فهرست عمومی + query؛ خروجی آرایهٔ CampaignSummary است، نه any.
  const campaigns: ApiOperation<"v1_campaigns_list">["response"] =
    await client.request("v1_campaigns_list", { query: { order: "fair", status: "active" } });
  void campaigns.length;

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

  // ۶) خطای RFC 9457 بهصورت تایپشده و با کد ماشینی پایدار قابل branching است.
  try {
    await client.request("v1_auth_otp_request", { body: { phone: "09121112233" } });
  } catch (error: unknown) {
    if (error instanceof ApiClientError) {
      const code: ProblemCode = error.code as ProblemCode;
      const trace: string = error.traceId;
      void code;
      void trace;
      void error.needsStepUp;
    }
  }
}

void integrationSmoke;
