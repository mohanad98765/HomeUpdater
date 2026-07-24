import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { solveProblem } from "./router";

// The switching/fallback core. jsdom has no navigator.gpu, so the local path is
// always "unsupported" here and must fall back to the cloud (or fail cleanly).
// The cloud provider is exercised through a mocked fetch.

let configured: boolean;
let reply: string;

function res(status: number, body: unknown, ok = status < 400): Response {
  return { ok, status, json: async () => body } as unknown as Response;
}

function router(url: RequestInfo | URL): Promise<Response> {
  const u = String(url);
  if (u.includes("/api/advisor/support/status")) return Promise.resolve(res(200, { configured }));
  if (u.includes("/api/advisor/support")) return Promise.resolve(res(200, { reply }));
  return Promise.resolve(res(404, {}));
}

beforeEach(() => {
  configured = true;
  reply = "Patch the firmware.";
  vi.stubGlobal("fetch", vi.fn(router));
});

afterEach(() => vi.restoreAllMocks());

describe("solveProblem router", () => {
  it("routes the cloud choice straight to the client's AI (no fallback)", async () => {
    const r = await solveProblem("cloud", { question: "q", context: "ctx" });
    expect(r.providerUsed).toBe("cloud");
    expect(r.fellBack).toBe(false);
    expect(r.answer).toBe("Patch the firmware.");
  });

  it("falls back to cloud when the local engine is unsupported (no WebGPU)", async () => {
    // jsdom exposes no navigator.gpu → localSupported() is false → fallback.
    const r = await solveProblem("local", { question: "q", context: "ctx" });
    expect(r.providerUsed).toBe("cloud");
    expect(r.fellBack).toBe(true);
    expect(r.answer).toBe("Patch the firmware.");
  });

  it("throws a clear error when neither local nor cloud is available", async () => {
    configured = false; // no advisor key → cloud unavailable, and no WebGPU
    await expect(solveProblem("local", { question: "q" })).rejects.toThrow(/تعذّر|WebGPU|سحاب/);
  });
});
