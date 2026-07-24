import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "@/lib/language";
import i18n from "@/i18n";
import { SupportPage } from "./SupportPage";

// The in-app help assistant: gated on an API key, sends usage questions to
// /api/advisor/support (no consent, no network data). Backend is fetch-mocked.

let configured = true;
let apiCalls: { url: string; method: string; body: Record<string, unknown> | undefined }[];

function res(status: number, body: unknown, ok = status < 400): Response {
  return { ok, status, json: async () => body } as unknown as Response;
}

function router(url: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const u = String(url);
  const m = (init?.method || "GET").toUpperCase();
  apiCalls.push({ url: u, method: m, body: init?.body ? JSON.parse(init.body as string) : undefined });
  if (u.includes("/api/advisor/support/status")) return Promise.resolve(res(200, { configured }));
  if (u.includes("/api/advisor/support")) return Promise.resolve(res(200, { reply: "Open the Devices page and scan." }));
  return Promise.resolve(res(404, {}));
}

function renderPage() {
  vi.stubGlobal("fetch", vi.fn(router));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <LanguageProvider>
        <SupportPage onBack={vi.fn()} />
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

const supportPosts = () => apiCalls.filter((c) => c.url.endsWith("/api/advisor/support") && c.method === "POST");

beforeAll(async () => {
  localStorage.setItem("homeupdater.language", "en");
  await i18n.changeLanguage("en");
});

beforeEach(() => {
  configured = true;
  apiCalls = [];
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("SupportPage", () => {
  it("disables input and shows the key hint when no API key is configured", async () => {
    configured = false;
    renderPage();
    expect(
      await screen.findByText("The assistant needs an Anthropic key — add it on the AI Advisor page."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Help assistant")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("sends a typed question and renders both bubbles", async () => {
    renderPage();
    const input = (await screen.findByLabelText("Help assistant")) as HTMLInputElement;
    await vi.waitFor(() => expect(input).toBeEnabled()); // status resolved → configured
    fireEvent.change(input, { target: { value: "how do I scan?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Open the Devices page and scan.")).toBeInTheDocument();
    expect(screen.getByText("how do I scan?")).toBeInTheDocument();
    const posts = supportPosts();
    expect(posts).toHaveLength(1);
    expect(posts[0].body).toEqual({ messages: [{ role: "user", content: "how do I scan?" }] });
    expect(input.value).toBe(""); // cleared on send
  });

  it("an example chip sends its preset question", async () => {
    renderPage();
    const chip = await screen.findByRole("button", { name: /How do I scan my network\?/ });
    await vi.waitFor(() => expect(chip).toBeEnabled());
    fireEvent.click(chip);
    expect(await screen.findByText("Open the Devices page and scan.")).toBeInTheDocument();
    const posts = supportPosts();
    expect(posts).toHaveLength(1);
    expect(posts[0].body).toEqual({
      messages: [{ role: "user", content: "How do I scan my network?" }],
    });
  });
});
