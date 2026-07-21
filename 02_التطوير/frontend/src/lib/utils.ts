import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * دمج classes مع حل التعارضات في Tailwind.
 * يُستخدم في جميع المكونات.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * تنسيق التاريخ بالعربية
 */
export function formatDateAr(date: Date | string): string {
  const d = typeof date === "string" ? new Date(date) : date;
  return new Intl.DateTimeFormat("ar-SA", {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

// --- Session token (see backend security_guard) ---------------------------
// The elevated API requires a per-launch secret so another local user/process
// can't drive it. The launcher passes it in our URL *fragment* (#t=…) — a
// fragment is never sent to the server nor in Referer headers. We stash it in
// sessionStorage and immediately clear the hash; apiFetch sends it on every call.
const TOKEN_KEY = "hu_session_token";

function initSessionToken(): void {
  try {
    const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : "";
    const t = new URLSearchParams(hash).get("t");
    if (t) {
      sessionStorage.setItem(TOKEN_KEY, t);
      // Drop the fragment so the token isn't left in the address bar / history.
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    }
  } catch {
    /* no window (SSR/tests) — ignore */
  }
}
initSessionToken();

function sessionToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

// --- App login token (user password gate; see services/auth.py) -----------
// Issued by /api/auth/login|setup, sent as X-HomeUpdater-Auth. Kept in
// sessionStorage so it survives a reload but clears when the app closes.
const AUTH_KEY = "hu_auth_token";

export function authToken(): string {
  try {
    return sessionStorage.getItem(AUTH_KEY) || "";
  } catch {
    return "";
  }
}

export function setAuthToken(token: string): void {
  try {
    if (token) sessionStorage.setItem(AUTH_KEY, token);
    else sessionStorage.removeItem(AUTH_KEY);
  } catch {
    /* ignore */
  }
}

/**
 * طلب API مع التعامل مع الأخطاء بشكل موحَّد
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = sessionToken();
  const auth = authToken();
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      // CSRF guard: the backend rejects state-changing requests without this
      // custom header. A cross-site page cannot set it without a CORS preflight,
      // which the backend's origin allowlist blocks.
      "X-HomeUpdater": "1",
      // Session auth: proves this is the legitimate UI, not another local process.
      ...(token ? { "X-HomeUpdater-Token": token } : {}),
      // App login token (user password gate).
      ...(auth ? { "X-HomeUpdater-Auth": auth } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    // The login session expired / is missing — drop it and ask the AuthGate to
    // show the login screen again (unless this WAS an auth call).
    if (res.status === 401 && !path.startsWith("/api/auth/")) {
      setAuthToken("");
      try {
        window.dispatchEvent(new Event("hu:unauthorized"));
      } catch {
        /* no window */
      }
    }
    const errorBody = await res.json().catch(() => ({}));
    // Backend HTTPException serializes as {"detail": ...}; the global handler
    // uses {"error": ...}. `detail` is usually a string, but some endpoints
    // (e.g. the advisor consent gate) return a structured object — coerce to a
    // readable string so `.message` stays useful, and expose the raw body +
    // status so callers can branch on structured errors (like consent_required).
    const detail = errorBody?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object"
          ? detail.message || detail.message_en || detail.error || `HTTP ${res.status}`
          : errorBody?.error || `HTTP ${res.status}`;
    const err = new Error(message) as ApiError;
    err.status = res.status;
    err.body = errorBody;
    throw err;
  }
  return res.json() as Promise<T>;
}

/** Error thrown by {@link apiFetch}. Carries the HTTP status and parsed body so
 * callers can branch on structured backend errors (not just the message). */
export interface ApiError extends Error {
  status?: number;
  body?: unknown;
}
