import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "@/lib/language";
import { ThemeProvider } from "@/lib/theme";
import i18n from "@/i18n";
import { QrPairing } from "./QrPairing";

// The panel shows a credential and then acts on what a network says, so the tests are
// about the moments where it could mislead or over-claim:
//   • it must not pretend to enable Developer options or Wireless debugging;
//   • when nothing arrives it must not guess a cause the hub cannot know;
//   • two phones must produce a question, never a silent pick;
//   • closing the panel must end the session, because a live code is a live credential.

let session: Record<string, unknown>;
let calls: string[];

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
  calls.push(`${method} ${u.split("?")[0]}`);
  if (u.includes("/pair/qr/choose")) {
    session = { ...session, status: "paired", device: { host: "192.168.3.11", port: 5555 } };
    return Promise.resolve(res(200, session));
  }
  if (u.includes("/pair/qr")) {
    if (method === "POST") {
      session = {
        id: "s1",
        payload: "WIFI:T:ADB;S:homeupdater-abc;P:123456;;",
        status: "waiting",
        seconds_left: 120,
        candidates: [],
      };
      return Promise.resolve(res(200, session));
    }
    if (method === "DELETE") return Promise.resolve(res(200, { cancelled: true }));
    return Promise.resolve(res(200, session));
  }
  return Promise.resolve(res(200, {}));
}

function renderPanel(onPaired = () => {}) {
  vi.stubGlobal("fetch", vi.fn(router));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <LanguageProvider>
          <QrPairing onPaired={onPaired} />
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
  session = { status: "none" };
  calls = [];
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("before a code exists", () => {
  it("offers the QR path without starting a session", async () => {
    renderPanel();
    expect(await screen.findByRole("button", { name: /show the pairing code/i })).toBeTruthy();
    expect(calls.filter((c) => c.startsWith("POST"))).toHaveLength(0);
  });
});

describe("while the code is up", () => {
  async function start() {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /show the pairing code/i }));
    await screen.findByAltText(/pairing code/i);
  }

  it("tells the user to turn Wireless debugging on themselves", async () => {
    await start();
    expect(screen.getByText(/Wireless debugging, and turn it on/i)).toBeTruthy();
    expect(screen.getByText(/Pair device with QR code/i)).toBeTruthy();
  });

  it("says plainly that it does not enable Developer options for you", async () => {
    await start();
    fireEvent.click(screen.getByText(/cannot find developer options/i));
    expect(screen.getByText(/does not turn it on for you/i)).toBeTruthy();
  });

  it("shows a countdown rather than an open-ended spinner", async () => {
    await start();
    expect(screen.getByText(/expires in 02:00/i)).toBeTruthy();
  });

  it("fetches the code as an image and never renders the payload as text", async () => {
    await start();
    expect(calls.some((c) => c === "GET /api/android/pair/qr.svg")).toBe(false);
    // jsdom does not fetch <img src>, so assert the element points at the endpoint and
    // that the raw payload is not sitting in the DOM for a screenshot to pick up.
    const img = screen.getByAltText(/pairing code/i) as HTMLImageElement;
    expect(img.getAttribute("src")).toContain("/api/android/pair/qr.svg");
    expect(document.body.textContent).not.toContain("WIFI:T:ADB");
  });
});

describe("when two phones arrive", () => {
  it("asks which one instead of picking", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /show the pairing code/i }));
    await screen.findByAltText(/pairing code/i);
    session = {
      ...session,
      status: "choose",
      candidates: [
        { instance: "adb-PHONE-A", address: "192.168.3.10", port: 1111 },
        { instance: "adb-PHONE-B", address: "192.168.3.11", port: 2222 },
      ],
    };
    // One poll interval (1500ms) has to elapse before the panel sees the new status.
    expect(await screen.findByText(/pick yours/i, {}, { timeout: 4000 })).toBeTruthy();
    expect(screen.getByText(/adb-PHONE-A/)).toBeTruthy();
    expect(screen.getByText(/adb-PHONE-B/)).toBeTruthy();
    expect(calls.some((c) => c.includes("/choose"))).toBe(false);

    fireEvent.click(screen.getByText(/adb-PHONE-B/));
    await waitFor(() => expect(calls.some((c) => c.includes("/choose"))).toBe(true));
  });
});

describe("when nothing arrives", () => {
  it("lists the causes rather than asserting one the hub cannot know", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /show the pairing code/i }));
    await screen.findByAltText(/pairing code/i);
    session = { ...session, status: "expired", seconds_left: 0 };
    expect(await screen.findByText(/no phone arrived/i, {}, { timeout: 4000 })).toBeTruthy();
    expect(screen.getByText(/never opened on the phone/i)).toBeTruthy();
    expect(screen.getByText(/different network/i)).toBeTruthy();
    expect(screen.getByText(/Windows Firewall/i)).toBeTruthy();
    expect(screen.getByText(/cannot tell these apart/i)).toBeTruthy();
  });
});

describe("the credential's lifetime", () => {
  it("hands the paired phone back so nothing is retyped", async () => {
    const onPaired = vi.fn();
    renderPanel(onPaired);
    fireEvent.click(await screen.findByRole("button", { name: /show the pairing code/i }));
    await screen.findByAltText(/pairing code/i);
    session = { ...session, status: "paired", device: { host: "192.168.3.30", port: 34677 } };
    await waitFor(() => expect(onPaired).toHaveBeenCalledWith("192.168.3.30", 34677), {
      timeout: 4000,
    });
  });

  it("ends the session when the panel goes away", async () => {
    const view = renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /show the pairing code/i }));
    await screen.findByAltText(/pairing code/i);
    view.unmount();
    await waitFor(() =>
      expect(calls.some((c) => c === "DELETE /api/android/pair/qr")).toBe(true),
    );
  });

  it("ends it on the close button too", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /show the pairing code/i }));
    await screen.findByAltText(/pairing code/i);
    fireEvent.click(screen.getByRole("button", { name: /close pairing/i }));
    await waitFor(() =>
      expect(calls.some((c) => c === "DELETE /api/android/pair/qr")).toBe(true),
    );
  });
});
