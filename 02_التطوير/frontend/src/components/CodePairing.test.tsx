import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "@/lib/language";
import { ThemeProvider } from "@/lib/theme";
import i18n from "@/i18n";
import { CodePairing } from "./CodePairing";

// The operator has no technical expertise — that is the constraint this panel exists to
// satisfy, so it is what these tests police. They assert the person is never asked for
// an address or a port, that the one number they do supply is validated before anything
// slow happens, and that a twenty-second scan announces itself rather than looking hung.

let candidates: Record<string, unknown>[];
let pairStatus: number;
let pairDelayMs: number;
let pairDetail: string;
let calls: { url: string; method: string; body: string }[];

function res(status: number, body: unknown, ok = status < 400): Response {
  return {
    ok,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

function router(url: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const u = String(url);
  const method = init?.method ?? "GET";
  calls.push({ url: u, method, body: String(init?.body ?? "") });
  if (u.includes("/pair/candidates")) {
    return Promise.resolve(res(200, { candidates, total: candidates.length }));
  }
  if (u.includes("/pair/auto")) {
    // The real call scans 20,000 ports; a fake that answers instantly would hide the
    // pending state entirely, which is the thing being asserted.
    const answer =
      pairStatus === 200
        ? res(200, { device: { host: "192.168.3.24", port: 34677 } })
        : res(pairStatus, { detail: pairDetail });
    return new Promise((resolve) => setTimeout(() => resolve(answer), pairDelayMs));
  }
  return Promise.resolve(res(200, {}));
}

function renderPanel(onAdded = () => {}) {
  vi.stubGlobal("fetch", vi.fn(router));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <LanguageProvider>
          <CodePairing onAdded={onAdded} />
        </LanguageProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

beforeAll(async () => {
  window.matchMedia =
    window.matchMedia ||
    ((query: string) =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList);
  localStorage.setItem("homeupdater.language", "en");
  await i18n.changeLanguage("en");
});

beforeEach(() => {
  candidates = [
    { ip: "192.168.3.24", name: "Samsung", vendor: "Samsung", device_type: "phone", already_added: false },
    { ip: "192.168.3.20", name: "Printer", vendor: "HP", device_type: "printer", already_added: false },
    { ip: "192.168.3.99", name: "Old phone", vendor: "Xiaomi", device_type: "phone", already_added: true },
  ];
  pairStatus = 200;
  pairDelayMs = 0;
  pairDetail = "";
  calls = [];
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("what the operator is asked for", () => {
  it("offers the phone as a choice — never an address to type", async () => {
    renderPanel();
    const picker = await screen.findByLabelText(/pick your phone/i);
    expect(picker.tagName).toBe("SELECT");
    expect(screen.getByText(/Samsung — 192\.168\.3\.24/)).toBeTruthy();
    // No free-text field for a host or a port anywhere in this panel.
    const inputs = Array.from(document.querySelectorAll("input"));
    expect(inputs).toHaveLength(1);
    expect(inputs[0].getAttribute("id")).toBe("code-pair-code");
  });

  it("separates real phones from everything else", async () => {
    renderPanel();
    await screen.findByLabelText(/pick your phone/i);
    const groups = Array.from(document.querySelectorAll("optgroup")).map((g) =>
      g.getAttribute("label"),
    );
    expect(groups).toEqual([expect.stringMatching(/phones/i), expect.stringMatching(/other/i)]);
    // A phone already in the list needs no pairing, so it is not offered first.
    expect(screen.getByText(/Old phone.*already added/i)).toBeTruthy();
  });

  it("accepts only six digits, and strips anything else as it is typed", async () => {
    renderPanel();
    await screen.findByLabelText(/pick your phone/i);
    const code = screen.getByLabelText(/six-digit code/i) as HTMLInputElement;
    fireEvent.change(code, { target: { value: "5a6b6c9d2e5f7g" } });
    expect(code.value).toBe("566925");
  });

  it("will not start a twenty-second scan on an incomplete code", async () => {
    renderPanel();
    await screen.findByLabelText(/pick your phone/i);
    fireEvent.change(screen.getByLabelText(/pick your phone/i), {
      target: { value: "192.168.3.24" },
    });
    fireEvent.change(screen.getByLabelText(/six-digit code/i), { target: { value: "566" } });
    const btn = screen.getByRole("button", { name: /pair and add/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.click(btn);
    expect(calls.some((c) => c.url.includes("/pair/auto"))).toBe(false);
  });
});

describe("pairing", () => {
  async function fill() {
    renderPanel();
    await screen.findByLabelText(/pick your phone/i);
    fireEvent.change(screen.getByLabelText(/pick your phone/i), {
      target: { value: "192.168.3.24" },
    });
    fireEvent.change(screen.getByLabelText(/six-digit code/i), { target: { value: "566925" } });
  }

  it("sends exactly the host and the code, and nothing else", async () => {
    await fill();
    fireEvent.click(screen.getByRole("button", { name: /pair and add/i }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/pair/auto"))).toBe(true));
    const sent = calls.find((c) => c.url.includes("/pair/auto"))!;
    expect(JSON.parse(sent.body)).toEqual({ host: "192.168.3.24", code: "566925" });
  });

  it("says how long the wait is, because a silent twenty seconds reads as hung", async () => {
    pairDelayMs = 400;  // still in flight while the assertion runs
    await fill();
    fireEvent.click(screen.getByRole("button", { name: /pair and add/i }));
    expect(await screen.findByText(/about 20 seconds/i)).toBeTruthy();
  });

  it("reports the server's sentence when pairing fails", async () => {
    pairStatus = 400;
    pairDetail = "the pairing screen is no longer open on the phone";
    await fill();
    fireEvent.click(screen.getByRole("button", { name: /pair and add/i }));
    expect(await screen.findByText(/no longer open on the phone/i)).toBeTruthy();
  });

  it("tells the caller the phone is in the list, so the page refreshes itself", async () => {
    const onAdded = vi.fn();
    renderPanel(onAdded);
    await screen.findByLabelText(/pick your phone/i);
    fireEvent.change(screen.getByLabelText(/pick your phone/i), {
      target: { value: "192.168.3.24" },
    });
    fireEvent.change(screen.getByLabelText(/six-digit code/i), { target: { value: "566925" } });
    fireEvent.click(screen.getByRole("button", { name: /pair and add/i }));
    await waitFor(() => expect(onAdded).toHaveBeenCalled());
  });
});

describe("when the app knows of no devices yet", () => {
  it("says where to go instead of showing an empty box", async () => {
    candidates = [];
    renderPanel();
    expect(await screen.findByText(/has not scanned your network yet/i)).toBeTruthy();
  });
});
