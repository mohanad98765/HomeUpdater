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

/**
 * طلب API مع التعامل مع الأخطاء بشكل موحَّد
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      // CSRF guard: the backend rejects state-changing requests without this
      // custom header. A cross-site page cannot set it without a CORS preflight,
      // which the backend's origin allowlist blocks.
      "X-HomeUpdater": "1",
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    // Backend HTTPException serializes as {"detail": ...}; the global handler
    // uses {"error": ...}. Read both so the user sees the real message.
    throw new Error(errorBody.detail || errorBody.error || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}
