import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch, cn, type ApiError } from "./utils";

function mockResponse(status: number, body: unknown, ok = false): Response {
  return { ok, status, json: async () => body } as Response;
}

afterEach(() => {
  vi.restoreAllMocks();
  try {
    sessionStorage.clear();
  } catch {
    /* jsdom always has sessionStorage */
  }
});

describe("cn", () => {
  it("joins truthy class names and drops falsy ones", () => {
    const out = cn("a", false && "b", undefined, "c");
    expect(out).toContain("a");
    expect(out).toContain("c");
    expect(out).not.toContain("b");
  });
});

describe("apiFetch", () => {
  it("resolves the parsed JSON on a 2xx response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse(200, { value: 42 }, true)));
    await expect(apiFetch<{ value: number }>("/api/x")).resolves.toEqual({ value: 42 });
  });

  it("throws a string message + status + body when detail is a string", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse(400, { detail: "bad input" })));
    await expect(apiFetch("/api/x")).rejects.toMatchObject({ message: "bad input", status: 400 });
  });

  it("coerces a STRUCTURED detail (consent gate) — never renders [object Object]", async () => {
    const body = {
      detail: { error: "consent_required", message_ar: "موافقة مطلوبة", message_en: "Consent required" },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse(403, body)));

    let err: ApiError | undefined;
    try {
      await apiFetch("/api/advisor/analyze");
    } catch (e) {
      err = e as ApiError;
    }
    expect(err).toBeDefined();
    expect(err!.message).not.toContain("[object Object]");
    expect(err!.message).toBe("Consent required"); // message_en fallback
    expect(err!.status).toBe(403);
    // Callers branch on the raw body (e.g. detail.error === "consent_required").
    expect((err!.body as typeof body).detail.error).toBe("consent_required");
  });

  it("falls back to the global-handler error field, else HTTP <status>", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse(500, { error: "boom" })));
    await expect(apiFetch("/api/x")).rejects.toMatchObject({ message: "boom" });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse(502, {})));
    await expect(apiFetch("/api/x")).rejects.toMatchObject({ message: "HTTP 502" });
  });

  it("on a 401 (non-auth path) clears the auth token and fires hu:unauthorized", async () => {
    sessionStorage.setItem("hu_auth_token", "stale-token");
    const onUnauth = vi.fn();
    window.addEventListener("hu:unauthorized", onUnauth);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse(401, { detail: "expired" })));

    await expect(apiFetch("/api/devices")).rejects.toBeTruthy();
    expect(sessionStorage.getItem("hu_auth_token")).toBeNull();
    expect(onUnauth).toHaveBeenCalledTimes(1);
    window.removeEventListener("hu:unauthorized", onUnauth);
  });
});
