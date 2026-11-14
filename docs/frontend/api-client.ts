/**
 * ═══════════════════════════════════════════════════════════════════════════
 * Crowdfunding-Back — کلاینت HTTP تایپشده، بدون هیچ وابستگی خارجی (Zero-Dependency)
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * ویژگیها:
 *  • تایپ کامل درخواست/پاسخ بر اساس `operationId` (از api-types.d.ts + operations.ts)
 *  • دو حالت احراز هویت: کوکی HttpOnly + CSRF، یا Bearer JWT موبایل/SPA
 *  • چرخش تکپروازهٔ refresh توکن (Single-Flight) با جلوگیری از حلقهٔ بیپایان
 *  • تبدیل تمام خطاها به ApiClientError با کد ماشینی پایدار RFC 9457
 *  • Idempotency-Key خودکار برای عملیات نوشتنی + بازارسال امن
 *  • ETag / If-None-Match و 304، تلاش مجدد نمایی برای 429/503، پیمایش مکاننمایی
 *
 * نحوهٔ استفاده: پوشهٔ `docs/frontend` را به `src/api` پروژهٔ خود کپی کنید و
 * مسیر importها را متناسب با ساختار پروژه تنظیم نمایید.
 */

import type { ApiError, ApiOperation, ApiOperationId, ApiOperationMap } from "./api-types";
import { OPERATIONS } from "./operations";
import type { HttpMethod } from "./operations";

/** خطای تایپشدهٔ سمت کلاینت؛ `code` مبنای branching در رابط کاربری است. */
export class ApiClientError extends Error {
  readonly code: string;
  readonly status: number;
  readonly traceId: string;
  readonly fieldErrors: Record<string, string[]>;
  readonly retryAfter: number | null;
  readonly problemType: string;

  constructor(problem: ApiError) {
    super(problem.detail || problem.title);
    this.name = "ApiClientError";
    this.code = problem.code;
    this.status = problem.status;
    this.traceId = problem.trace_id;
    this.fieldErrors = problem.errors ?? {};
    this.retryAfter = problem.retry_after ?? null;
    this.problemType = problem.type;
  }

  /** آیا این خطا نیازمند باز کردن مودال TOTP و بازارسال همان درخواست است؟ */
  get needsStepUp(): boolean {
    return this.code === "mfa_required" || this.code === "step_up_required";
  }

  /** آیا نشست کاملاً باطل شده و باید به جریان ورود هدایت شد؟ */
  get isSessionExpired(): boolean {
    return (
      this.status === 401 &&
      (this.code === "authentication_required" || this.code === "user_inactive")
    );
  }
}

export type AuthMode = "cookie" | "bearer";

export interface TokenPair {
  accessToken: string;
  refreshToken: string;
}

export interface ApiClientOptions {
  /** آدرس پایه، همان `servers[0].url` در OpenAPI (مثلاً https://api.charity.example.org). */
  baseUrl: string;
  authMode: AuthMode;
  /** حافظهٔ توکنها؛ در مرورگر ترجیحاً حافظهٔ درونبرنامهای بههمراه کوکی HttpOnly. */
  getTokens?: () => TokenPair | null;
  setTokens?: (tokens: TokenPair | null) => void;
  /** فراخوانی هنگام ابطال کامل نشست (پاکسازی استور و هدایت به /login). */
  onSessionExpired?: () => void;
  /** فراخوانی هنگام نیاز به Step-Up MFA (باز کردن مودال کد ۶ رقمی). */
  onStepUpRequired?: () => void | Promise<void>;
  fetchImpl?: typeof fetch;
  /** حداکثر تلاش مجدد برای 429/503/5xx (پیشفرض ۲). */
  maxRetries?: number;
}

export interface RequestOptions<K extends ApiOperationId> {
  /** مقادیر پارامترهای مسیر، مثلاً { identifier: "my-slug" }. */
  params?: Record<string, string | number>;
  body?: ApiOperation<K>["request"];
  query?: Record<string, string | number | boolean | undefined>;
  /** هدر Idempotency-Key؛ اگر خالی بماند برای متدهای نوشتنی خودکار ساخته میشود. */
  idempotencyKey?: string;
  /** غیرفعالسازی تلاش مجدد خودکار (برای عملیات بسیار حساس). */
  noRetry?: boolean;
  signal?: AbortSignal;
}

interface InternalState {
  csrfToken: string | null;
  csrfPending: Promise<string> | null;
  refreshPending: Promise<boolean> | null;
  etags: Map<string, { etag: string; value: unknown }>;
}

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

const makeIdempotencyKey = (): string =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `idem-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;

const interpolate = (path: string, params?: Record<string, string | number>): string =>
  path.replace(/\{([^}]+)\}/g, (_match, key: string) => {
    const value = params?.[key];
    if (value === undefined) {
      throw new Error(`Missing path parameter: ${key}`);
    }
    return encodeURIComponent(String(value));
  });

export function createApiClient(options: ApiClientOptions) {
  const doFetch = options.fetchImpl ?? fetch.bind(globalThis);
  const maxRetries = options.maxRetries ?? 2;
  const state: InternalState = {
    csrfToken: null,
    csrfPending: null,
    refreshPending: null,
    etags: new Map(),
  };

  const buildUrl = (
    path: string,
    query?: RequestOptions<ApiOperationId>["query"],
  ): string => {
    const url = new URL(path.replace(/^\//, ""), options.baseUrl.replace(/\/?$/, "/"));
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
    return url.toString();
  };

  /** کاشت یکبارهٔ توکن CSRF (تکپروازه، ایمن در برابر چند درخواست همزمان آغازین). */
  const ensureCsrf = async (): Promise<string> => {
    if (options.authMode !== "cookie") return "";
    if (state.csrfToken) return state.csrfToken;
    if (!state.csrfPending) {
      state.csrfPending = (async () => {
        const res = await doFetch(buildUrl("/api/v1/auth/csrf"), {
          credentials: "include",
          headers: { Accept: "application/json" },
        });
        if (!res.ok) throw new Error("CSRF bootstrap failed");
        const data = (await res.json()) as { csrf_token: string };
        state.csrfToken = data.csrf_token;
        return data.csrf_token;
      })().finally(() => {
        state.csrfPending = null;
      });
    }
    return state.csrfPending;
  };

  /** چرخش توکن refresh بهصورت Single-Flight: تمام درخواستهای 401 منتظر یک چرخش میمانند. */
  const rotateTokens = async (): Promise<boolean> => {
    if (options.authMode !== "bearer") return false;
    if (state.refreshPending) return state.refreshPending;
    const current = options.getTokens?.();
    if (!current?.refreshToken) return false;
    state.refreshPending = (async () => {
      const res = await doFetch(buildUrl("/api/v1/auth/token/refresh"), {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ refresh_token: current.refreshToken }),
      });
      if (!res.ok) {
        options.setTokens?.(null);
        options.onSessionExpired?.();
        return false;
      }
      const data = (await res.json()) as {
        access_token: string;
        refresh_token: string;
      };
      options.setTokens?.({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
      });
      return true;
    })().finally(() => {
      state.refreshPending = null;
    });
    return state.refreshPending;
  };

  const parseProblem = async (res: Response): Promise<ApiClientError> => {
    try {
      const body = (await res.json()) as Partial<ApiError>;
      return new ApiClientError({
        type: body.type ?? "about:blank",
        title: body.title ?? "خطا",
        status: body.status ?? res.status,
        detail: body.detail ?? "خطای ناشناختهای رخ داد.",
        code: (body.code ?? "internal_error") as ApiError["code"],
        instance: body.instance ?? "",
        trace_id: body.trace_id ?? res.headers.get("X-Request-ID") ?? "",
        errors: body.errors,
        retry_after: body.retry_after,
      });
    } catch {
      return new ApiClientError({
        type: "about:blank",
        title: "پاسخ غیرقابلپارس",
        status: res.status,
        detail: "پاسخ سرور در قالب استاندارد نبود.",
        code: "internal_error",
        instance: "",
        trace_id: res.headers.get("X-Request-ID") ?? "",
      });
    }
  };

  const buildHeaders = async (
    method: HttpMethod,
    hasBody: boolean,
    idempotencyKey?: string,
    etag?: string,
  ): Promise<Record<string, string>> => {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (hasBody) headers["Content-Type"] = "application/json";
    if (options.authMode === "bearer") {
      const tokens = options.getTokens?.();
      if (tokens?.accessToken) headers.Authorization = `Bearer ${tokens.accessToken}`;
    } else if (method !== "GET") {
      // توکن CSRF فقط برای متدهای نوشتنی لازم است؛ GET اضافهای به سرور نمیشود.
      headers["X-CSRFToken"] = await ensureCsrf();
      if (!headers["X-CSRFToken"]) throw new Error("CSRF token unavailable");
    }
    if (method !== "GET") {
      headers["Idempotency-Key"] = idempotencyKey ?? makeIdempotencyKey();
    }
    if (etag) headers["If-None-Match"] = etag;
    return headers;
  };

  /** هستهٔ فراخوانی: تایپشده، مقاوم، با تلاش مجدد هوشمند و خطای ساختاریافته. */
  async function request<K extends ApiOperationId>(
    operationId: K,
    opts: RequestOptions<K> = {},
  ): Promise<ApiOperation<K>["response"]> {
    const descriptor = OPERATIONS[operationId];
    const method = descriptor.method as HttpMethod;
    const path = interpolate(descriptor.path, opts.params);
    const cacheKey = `${method} ${buildUrl(path, opts.query)}`;
    const cached = method === "GET" ? state.etags.get(cacheKey) : undefined;
    let refreshed = false;

    for (let attempt = 0; attempt <= maxRetries; attempt += 1) {
      const headers = await buildHeaders(
        method,
        opts.body !== undefined,
        opts.idempotencyKey,
        cached?.etag,
      );
      const init: RequestInit = {
        method,
        headers,
        credentials: options.authMode === "cookie" ? "include" : "omit",
        signal: opts.signal,
      };
      if (opts.body !== undefined) init.body = JSON.stringify(opts.body);

      const res = await doFetch(buildUrl(path, opts.query), init);

      if (res.status === 304 && cached) {
        return cached.value as ApiOperation<K>["response"];
      }

      if (res.ok) {
        if (res.status === 204) return undefined as ApiOperation<K>["response"];
        const contentType = res.headers.get("Content-Type") ?? "";
        const value = contentType.includes("json") ? await res.json() : await res.blob();
        const etag = res.headers.get("ETag");
        if (method === "GET" && etag) state.etags.set(cacheKey, { etag, value });
        return value as ApiOperation<K>["response"];
      }

      const problem = await parseProblem(res);

      // 401 → دقیقاً یکبار چرخش توکن و سپس بازارسال همان درخواست (بدون حلقه)
      if (problem.isSessionExpired && !refreshed && (await rotateTokens())) {
        refreshed = true;
        attempt -= 1;
        continue;
      }
      if (problem.isSessionExpired) options.onSessionExpired?.();

      // 403 Step-Up → مودال TOTP، سپس همان درخواست با همان Idempotency-Key
      if (problem.needsStepUp && !opts.noRetry && options.onStepUpRequired) {
        await options.onStepUpRequired();
        if (attempt < maxRetries) {
          await sleep(150);
          continue;
        }
      }

      // 429 / 503 / 5xx → backoff نمایی با رعایت Retry-After
      const retryable = [429, 503].includes(res.status) || res.status >= 500;
      if (retryable && !opts.noRetry && attempt < maxRetries) {
        const waitMs = (problem.retryAfter ?? 2 ** attempt) * 1000;
        await sleep(Math.min(waitMs, 15_000));
        continue;
      }
      throw problem;
    }
    throw new Error("Request retry budget exhausted");
  }

  /** کمکی: پیمایش تمام صفحات مکاننمایی بدون دستکاری دستی cursor. */
  async function* paginate<K extends ApiOperationId>(
    operationId: K,
    opts: RequestOptions<K> & { query?: Record<string, string> } = {},
  ): AsyncGenerator<ApiOperation<K>["response"]> {
    let nextUrl: string | null = null;
    let first = true;
    while (first || nextUrl) {
      first = false;
      const query: Record<string, string> = { ...(opts.query ?? {}) };
      if (nextUrl) {
        new URL(nextUrl).searchParams.forEach((value, key) => {
          query[key] = value;
        });
      }
      const page = (await request(operationId, { ...opts, query })) as {
        results: unknown[];
        meta: { next: string | null };
      };
      yield page as ApiOperation<K>["response"];
      nextUrl = page.meta.next;
    }
  }

  return {
    request,
    paginate,
    ensureCsrf,
    resetCsrf: () => {
      state.csrfToken = null;
    },
    invalidateCache: () => state.etags.clear(),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
export type { ApiOperationMap, HttpMethod };
export { OPERATIONS };
