import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "@/lib/language";
import i18n from "@/i18n";
import { AdvisorPage } from "./AdvisorPage";

// AdvisorPage is the competition centerpiece: the agentic advisor UI. These
// tests lock its contracts against a mocked backend — the API-key gate, the
// T11 data-sharing consent gate (every branch), the analyze pipeline (trace
// badges + provenance + truncation), the one-click Apply flow (window.confirm
// both directions + count interpolation), and the chat. Backend is fetch-mocked.

// ---------------------------------------------------------------------------
// Shared harness
// ---------------------------------------------------------------------------

function res(status: number, body: unknown, ok = status < 400): Response {
  return { ok, status, json: async () => body } as unknown as Response;
}

interface Recorded {
  url: string;
  method: string;
  body: Record<string, unknown> | undefined;
}

// Per-test scenario knobs — reset in beforeEach.
let status: { configured: boolean; model: string; env: boolean; consented: boolean };
let analyzeRes: Response;
let applyRes: Response;
let chatRes: Response;
let keyRes: Response;
let consentRes: Response;
let consentTextRes: Response;
let apiCalls: Recorded[];

// The fetch router MUST branch on BOTH path AND method: "/api/advisor/consent"
// is a substring of "/api/advisor/consent-text", so consent-text (GET) is
// matched first and the consent write is gated on POST.
function router(url: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const u = String(url);
  const m = (init?.method || "GET").toUpperCase();
  let body: Record<string, unknown> | undefined;
  try {
    body = init?.body ? (JSON.parse(init.body as string) as Record<string, unknown>) : undefined;
  } catch {
    body = undefined;
  }
  apiCalls.push({ url: u, method: m, body });

  if (u.includes("/api/advisor/status")) return Promise.resolve(res(200, status));
  if (u.includes("/api/advisor/consent-text")) return Promise.resolve(consentTextRes);
  if (u.includes("/api/advisor/consent") && m === "POST") return Promise.resolve(consentRes);
  if (u.includes("/api/advisor/analyze") && m === "POST") return Promise.resolve(analyzeRes);
  if (u.includes("/api/advisor/apply") && m === "POST") return Promise.resolve(applyRes);
  if (u.includes("/api/advisor/chat") && m === "POST") return Promise.resolve(chatRes);
  if (u.includes("/api/advisor/key") && m === "POST") return Promise.resolve(keyRes);
  return Promise.resolve(res(404, {}));
}

function callsTo(frag: string, method?: string): Recorded[] {
  return apiCalls.filter((c) => c.url.includes(frag) && (!method || c.method === method));
}

function renderPage() {
  vi.stubGlobal("fetch", vi.fn(router));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onBack = vi.fn();
  const utils = render(
    <QueryClientProvider client={qc}>
      <LanguageProvider>
        <AdvisorPage onBack={onBack} />
      </LanguageProvider>
    </QueryClientProvider>,
  );
  return { ...utils, onBack };
}

beforeAll(async () => {
  try {
    localStorage.setItem("homeupdater.language", "en"); // stable English assertions + dir=ltr
  } catch {
    /* jsdom always has localStorage */
  }
  await i18n.changeLanguage("en");
});

beforeEach(() => {
  status = { configured: true, model: "claude-3-5", env: true, consented: true };
  analyzeRes = res(200, { recommendations: "ok", trace: [], model: "m", actions: [] });
  applyRes = res(200, { applied: 0, skipped: [] });
  chatRes = res(200, { reply: "ok" });
  keyRes = res(200, {});
  consentRes = res(200, { consented: true });
  consentTextRes = res(200, { ar: "موافقة المشاركة", en: "CONSENT BODY", consented: true });
  apiCalls = [];
  try {
    sessionStorage.clear();
  } catch {
    /* jsdom */
  }
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks(); // also removes any window.confirm spy
});

const analyzeBtn = () => screen.findByRole("button", { name: "Analyze my network" });

describe("AdvisorPage", () => {
  // -------------------------------------------------------------------------
  // Key-entry gate
  // -------------------------------------------------------------------------
  it("C1: unconfigured shows only the API-key gate; Save length-gates + trims + clears; no cloud call", async () => {
    status = { configured: false, model: "", env: false, consented: false };
    keyRes = res(200, {});
    renderPage();

    const input = (await screen.findByLabelText("Anthropic API key")) as HTMLInputElement;
    const saveBtn = screen.getByRole("button", { name: "Save key" });
    expect(saveBtn).toBeDisabled(); // empty
    fireEvent.change(input, { target: { value: "1234567" } }); // 7 chars
    expect(saveBtn).toBeDisabled();
    fireEvent.change(input, { target: { value: "  sk-ant-abcd  " } }); // 11 trimmed
    expect(saveBtn).toBeEnabled();

    // Nothing cloud-facing is reachable before a key exists.
    expect(screen.queryByRole("button", { name: "Analyze my network" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Ask the Advisor" })).toBeNull();
    expect(screen.queryByText("Applicable plan")).toBeNull();
    expect(screen.queryByText("Advisor steps")).toBeNull();

    fireEvent.click(saveBtn);
    await waitFor(() => expect(input.value).toBe("")); // onSuccess clears the field

    const keyPosts = callsTo("/api/advisor/key", "POST");
    expect(keyPosts).toHaveLength(1);
    expect((keyPosts[0].body as { key: string }).key).toBe("sk-ant-abcd"); // trimmed
    expect(callsTo("/api/advisor/analyze")).toHaveLength(0);
    expect(callsTo("/api/advisor/chat")).toHaveLength(0);
    expect(callsTo("/api/advisor/consent-text")).toHaveLength(0); // query disabled while unconfigured
  });

  it("C13: saveKey error shows the danger message and keeps the typed key", async () => {
    status = { configured: false, model: "", env: false, consented: false };
    keyRes = res(400, { detail: "Invalid API key" });
    renderPage();

    const input = (await screen.findByLabelText("Anthropic API key")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "sk-ant-abcd12" } });
    fireEvent.click(screen.getByRole("button", { name: "Save key" }));

    await screen.findByText("Invalid API key");
    expect(input.value).toBe("sk-ant-abcd12"); // error path skips the clear
  });

  // -------------------------------------------------------------------------
  // Configured layout + analyze pipeline
  // -------------------------------------------------------------------------
  it("C2: configured + consented shows Analyze + chat + Revoke; hides key/review/plan; no premature analyze", async () => {
    consentTextRes = res(200, { ar: "موافقة", en: "We share device data with Claude.", consented: true });
    renderPage();

    await analyzeBtn();
    expect(screen.getByRole("heading", { name: "Ask the Advisor" })).toBeInTheDocument();
    expect(screen.getByLabelText("Ask the Advisor")).toBeInTheDocument(); // chat input
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revoke consent" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "AI Advisor" })).toBeInTheDocument();

    expect(screen.queryByLabelText("Anthropic API key")).toBeNull();
    expect(screen.queryByRole("button", { name: "Review consent & continue" })).toBeNull();
    expect(screen.queryByText("Applicable plan")).toBeNull();
    expect(screen.queryByText("Advisor steps")).toBeNull();
    expect(callsTo("/api/advisor/analyze")).toHaveLength(0);
  });

  it("C3: analyze happy path renders recs + all tool badges (unknown→fallback) + provenance; body {lang:en}; Export no-throw", async () => {
    analyzeRes = res(200, {
      recommendations: "Patch the router firmware tonight.",
      trace: [
        { tool: "list_devices" },
        { tool: "check_vulnerabilities" },
        { tool: "list_pending_updates" },
        { tool: "set_plan" },
        { tool: "mystery_tool" },
      ],
      model: "claude-sonnet-4-5",
      actions: [],
    });
    renderPage();

    fireEvent.click(await analyzeBtn());
    await screen.findByText("Patch the router firmware tonight.");

    expect(screen.getByText("Advisor steps")).toBeInTheDocument();
    expect(screen.getByText("Checking vulnerabilities")).toBeInTheDocument();
    expect(screen.getByText("Listing pending updates")).toBeInTheDocument();
    expect(screen.getByText("Building the plan")).toBeInTheDocument();
    // list_devices + the unknown "mystery_tool" fallback both label "Reading devices".
    expect(screen.getAllByText("Reading devices")).toHaveLength(2);
    // Provenance line mixes an icon with the text, so match the whole span.
    expect(screen.getByText(/Powered by Claude · claude-sonnet-4-5/)).toBeInTheDocument();

    const a = callsTo("/api/advisor/analyze", "POST");
    expect(a).toHaveLength(1);
    expect((a[0].body as { lang: string }).lang).toBe("en");

    expect(screen.queryByText(/The recommendation may be incomplete/)).toBeNull();
    expect(screen.queryByText("Applicable plan")).toBeNull(); // no actions

    // Export uses a hidden iframe + a deferred print(); fake timers keep the
    // jsdom-unimplemented print from firing after the test. Contract: no throw.
    const exportBtn = screen.getByRole("button", { name: "Export PDF report" });
    vi.useFakeTimers();
    try {
      expect(() => fireEvent.click(exportBtn)).not.toThrow();
    } finally {
      vi.useRealTimers();
    }
  });

  it("C12: truncation warning renders when analyze returns truncated:true", async () => {
    analyzeRes = res(200, {
      recommendations: "Short plan.",
      trace: [{ tool: "set_plan" }],
      model: "m",
      truncated: true,
      actions: [],
    });
    renderPage();

    fireEvent.click(await analyzeBtn());
    await screen.findByText("Short plan.");
    expect(screen.getByText(/The recommendation may be incomplete/)).toBeInTheDocument();
  });

  it("C10: analyze 500 shows 'Analysis failed: <msg>' and does NOT open the consent modal", async () => {
    analyzeRes = res(500, { detail: "model overloaded" });
    renderPage();

    fireEvent.click(await analyzeBtn());
    await screen.findByText(/Analysis failed:\s*model overloaded/);
    expect(screen.queryByRole("heading", { name: "Data-sharing consent" })).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Apply flow
  // -------------------------------------------------------------------------
  it("C4: plan slices top-3; confirm=false → no POST; confirm=true → POST 3 actions → applied+skipped; button replaced", async () => {
    analyzeRes = res(200, {
      recommendations: "Plan ready.",
      trace: [{ tool: "set_plan" }],
      model: "m",
      actions: [
        { type: "app", id: "1", title: "Update Chrome", reason: "critical CVE" },
        { type: "windows", id: "2", title: "Windows security update" },
        { type: "app", id: "3", title: "Update VLC" },
        { type: "app", id: "4", title: "Update 7-Zip" },
      ],
    });
    applyRes = res(200, { applied: 2, skipped: ["KB5001"] });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValue(true);
    renderPage();

    fireEvent.click(await analyzeBtn());
    const applyBtn = await screen.findByRole("button", { name: "Apply top 3 updates" });
    expect(screen.getByText("Update Chrome")).toBeInTheDocument();
    expect(screen.getByText("Windows security update")).toBeInTheDocument();
    expect(screen.getByText("Update VLC")).toBeInTheDocument();
    expect(screen.getByText(/critical CVE/)).toBeInTheDocument(); // optional reason on Chrome
    expect(screen.queryByText("Update 7-Zip")).toBeNull(); // slice(0,3) drops the 4th

    // Declined at the confirm() prompt → nothing installed.
    fireEvent.click(applyBtn);
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(callsTo("/api/advisor/apply", "POST")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Apply top 3 updates" })).toBeInTheDocument();

    // Accepted → POSTs exactly the three top actions.
    fireEvent.click(screen.getByRole("button", { name: "Apply top 3 updates" }));
    await screen.findByText(/Applied 2 update\(s\)/);
    expect(screen.getByText(/skipped 1 \(no longer pending\)/)).toBeInTheDocument();

    const ap = callsTo("/api/advisor/apply", "POST");
    expect(ap).toHaveLength(1);
    const sent = (ap[0].body as { actions: { title: string }[] }).actions;
    expect(sent).toHaveLength(3);
    expect(sent.map((x) => x.title)).toEqual(["Update Chrome", "Windows security update", "Update VLC"]);
    expect(screen.queryByRole("button", { name: "Apply top 3 updates" })).toBeNull(); // replaced by the result line
  });

  it("C14: apply error shows 'Apply failed: <msg>' and keeps the Apply button (retry affordance)", async () => {
    analyzeRes = res(200, {
      recommendations: "Plan.",
      trace: [{ tool: "set_plan" }],
      model: "m",
      actions: [{ type: "app", id: "1", title: "Update Chrome" }],
    });
    applyRes = res(500, { detail: "Install service unavailable" });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();

    fireEvent.click(await analyzeBtn());
    fireEvent.click(await screen.findByRole("button", { name: "Apply top 3 updates" }));
    await screen.findByText(/Apply failed:\s*Install service unavailable/);
    expect(screen.getByRole("button", { name: "Apply top 3 updates" })).toBeInTheDocument();
    expect(screen.queryByText(/Applied \d/)).toBeNull();
  });

  it("C16: re-analyzing resets a prior apply result (no stale 'Applied N' on the new plan)", async () => {
    analyzeRes = res(200, {
      recommendations: "Plan A",
      trace: [{ tool: "list_devices" }],
      model: "m",
      actions: [{ type: "app", id: "1", title: "Update Chrome" }],
    });
    applyRes = res(200, { applied: 2, skipped: [] });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();

    fireEvent.click(await analyzeBtn());
    fireEvent.click(await screen.findByRole("button", { name: "Apply top 3 updates" }));
    await screen.findByText(/Applied 2 update\(s\)/);

    // Fresh analysis → onMutate apply.reset() → the "Applied" line clears, Apply returns.
    fireEvent.click(screen.getByRole("button", { name: "Analyze my network" }));
    await waitFor(() => expect(screen.queryByText(/Applied 2 update\(s\)/)).toBeNull());
    expect(await screen.findByRole("button", { name: "Apply top 3 updates" })).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // T11 — data-sharing consent gate
  // -------------------------------------------------------------------------
  it("C5: needsConsent hides Analyze/Revoke, shows Review + warning; opening the modal makes no cloud call", async () => {
    status = { configured: true, model: "claude-x", env: true, consented: false };
    consentTextRes = res(200, { ar: "نص الموافقة", en: "CONSENT BODY", consented: false });
    renderPage();

    const review = await screen.findByRole("button", { name: "Review consent & continue" });
    expect(screen.queryByRole("button", { name: "Analyze my network" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Revoke consent" })).toBeNull();
    expect(
      screen.getByText("The Advisor needs your consent to share data before it can analyze or chat."),
    ).toBeInTheDocument();

    fireEvent.click(review);
    await screen.findByRole("heading", { name: "Data-sharing consent" });
    expect(callsTo("/api/advisor/analyze")).toHaveLength(0);
    expect(callsTo("/api/advisor/chat")).toHaveLength(0);
  });

  it("C6: sendChat under needsConsent opens the modal, POSTs nothing to /chat, and keeps the typed text", async () => {
    status = { configured: true, model: "m", env: true, consented: false };
    consentTextRes = res(200, { ar: "نص", en: "CONSENT BODY", consented: false });
    renderPage();

    const input = (await screen.findByLabelText("Ask the Advisor")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "riskiest device?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await screen.findByRole("heading", { name: "Data-sharing consent" });
    expect(callsTo("/api/advisor/chat")).toHaveLength(0); // nothing left before consent
    expect(input.value).toBe("riskiest device?"); // not cleared (returned before send)
  });

  it("C7: analyze 403 consent_required opens the modal and suppresses the failure banner (POST did fire)", async () => {
    analyzeRes = res(403, { detail: { error: "consent_required" } });
    renderPage();

    fireEvent.click(await analyzeBtn());
    await screen.findByRole("heading", { name: "Data-sharing consent" });
    expect(callsTo("/api/advisor/analyze", "POST")).toHaveLength(1); // gate is server-side
    expect(screen.queryByText("Analysis failed:", { exact: false })).toBeNull();
  });

  it("C8: accepting consent POSTs exactly {consented:true} and closes the modal", async () => {
    status = { configured: true, model: "m", env: true, consented: false };
    consentTextRes = res(200, { ar: "نص", en: "CONSENT BODY", consented: false });
    consentRes = res(200, { consented: true });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Review consent & continue" }));
    await screen.findByText("CONSENT BODY"); // body loaded → "I agree" enabled
    const agree = screen.getByRole("button", { name: "I agree" });
    expect(agree).toBeEnabled();
    fireEvent.click(agree);

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Data-sharing consent" })).toBeNull(),
    );
    const c = callsTo("/api/advisor/consent", "POST");
    expect(c).toHaveLength(1);
    expect(c[0].body).toEqual({ consented: true });
  });

  it("C15: declining the consent gate closes the modal and writes NOTHING to /consent", async () => {
    status = { configured: true, model: "m", env: true, consented: false };
    consentTextRes = res(200, { ar: "نص", en: "CONSENT BODY", consented: false });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Review consent & continue" }));
    await screen.findByRole("heading", { name: "Data-sharing consent" });
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Data-sharing consent" })).toBeNull(),
    );
    expect(callsTo("/api/advisor/consent", "POST")).toHaveLength(0); // walking away ≠ consent
  });

  it("C9: 'Revoke consent' shows only when consented and POSTs exactly {consented:false}", async () => {
    status = { configured: true, model: "m", env: true, consented: true };
    consentRes = res(200, { consented: false });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Revoke consent" }));
    await waitFor(() => expect(callsTo("/api/advisor/consent", "POST")).toHaveLength(1));
    expect(callsTo("/api/advisor/consent", "POST")[0].body).toEqual({ consented: false });
    expect(
      screen.queryByText("The Advisor needs your consent to share data before it can analyze or chat."),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Review consent & continue" })).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Chat
  // -------------------------------------------------------------------------
  it("C11: chat Send disabled while empty/whitespace; typing + Enter POSTs history, appends both bubbles, clears input", async () => {
    chatRes = res(200, { reply: "Your riskiest device is the router." });
    renderPage();

    const input = (await screen.findByLabelText("Ask the Advisor")) as HTMLInputElement;
    const send = screen.getByRole("button", { name: "Send" });
    expect(send).toBeDisabled(); // empty
    fireEvent.change(input, { target: { value: "   " } });
    expect(send).toBeDisabled(); // whitespace-only
    fireEvent.keyDown(input, { key: "Enter" });
    expect(callsTo("/api/advisor/chat")).toHaveLength(0); // early-return on empty trim

    fireEvent.change(input, { target: { value: "which device?" } });
    expect(send).toBeEnabled();
    fireEvent.keyDown(input, { key: "Enter" });

    await screen.findByText("Your riskiest device is the router."); // assistant bubble
    expect(screen.getByText("which device?")).toBeInTheDocument(); // user bubble
    const c = callsTo("/api/advisor/chat", "POST");
    expect(c).toHaveLength(1);
    expect(c[0].body).toEqual({ messages: [{ role: "user", content: "which device?" }] });
    expect(input.value).toBe(""); // cleared on send
  });

  it("C17: chat 500 renders 'Analysis failed: <msg>' under the chat and opens no modal", async () => {
    chatRes = res(500, { detail: "model overloaded" });
    renderPage();

    const input = (await screen.findByLabelText("Ask the Advisor")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "which device?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await screen.findByText(/Analysis failed:\s*model overloaded/);
    expect(screen.queryByRole("heading", { name: "Data-sharing consent" })).toBeNull();
  });

  it("C18: chat 403 consent_required opens the modal and suppresses the chat error banner (POST fired)", async () => {
    chatRes = res(403, { detail: { error: "consent_required" } });
    renderPage();

    const input = (await screen.findByLabelText("Ask the Advisor")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "which device?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await screen.findByRole("heading", { name: "Data-sharing consent" });
    expect(callsTo("/api/advisor/chat", "POST")).toHaveLength(1);
    expect(screen.queryByText("Analysis failed:", { exact: false })).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Navigation
  // -------------------------------------------------------------------------
  it("C19: the back button calls onBack", async () => {
    const { onBack } = renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Dashboard" }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
