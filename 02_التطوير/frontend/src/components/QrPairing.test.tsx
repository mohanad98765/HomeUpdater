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
let bodies: string[];

function res(status: number, body: unknown, ok = status < 400): Response {
  return {
    ok,
    status,
    json: async () => body,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  } as unknown as Response;
}

function router(url: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const u = String(url);
  const method = init?.method ?? "GET";
  calls.push(`${method} ${u.split("?")[0]}`);
  if (typeof init?.body === "string") bodies.push(init.body);
  if (u.includes("/pair/candidates")) {
    return Promise.resolve(
      res(200, {
        candidates: [
          { ip: "192.168.3.24", name: "Galaxy", device_type: "phone", already_added: false },
          { ip: "192.168.3.7", name: "Printer", device_type: "printer", already_added: true },
        ],
      }),
    );
  }
  if (u.includes("/pair/qr.svg")) {
    // The app's API rejects anything without the per-launch session token. An <img src>
    // cannot send it, so this fake refuses that case the way the real server does — the
    // whole point of the assertions below.
    const headers = (init?.headers ?? {}) as Record<string, string>;
    if (!headers["X-HomeUpdater"]) {
      return Promise.resolve(res(401, { detail: "Missing or invalid session token" }));
    }
    return Promise.resolve(
      res(200, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 41 41"></svg>'),
    );
  }
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
  bodies = [];
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
    await screen.findByRole("img", { name: /pairing code/i });
  }

  it("tells the user to turn Wireless debugging on themselves", async () => {
    await start();
    expect(screen.getByText(/Wireless debugging, and turn it on/i)).toBeTruthy();
    // Named in both the warning and the step, deliberately — see the next test.
    expect(screen.getAllByText(/Pair device with QR code/i).length).toBeGreaterThan(0);
  });

  it("warns that the camera app cannot work, before the steps", async () => {
    // The payload begins with the literal "WIFI:" prefix, so a camera app or any QR
    // reader treats it as a Wi-Fi join code and never reaches adb. Five real sessions
    // expired unused for exactly this reason, with the code rendering perfectly. This
    // one sentence is the difference between the feature working and not, so it is
    // asserted to be present, prominent, and ahead of the numbered steps.
    await start();
    const warning = screen.getByText(/will not work/i);
    expect(warning).toBeTruthy();
    expect(warning.textContent).toMatch(/camera app|QR reader/i);

    const steps = screen.getByRole("list");
    expect(
      warning.compareDocumentPosition(steps) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
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

  it("fetches the code THROUGH the authenticated client, not as an <img src>", async () => {
    // This replaces an assertion that encoded the shipped bug: it asserted the request
    // did NOT happen, excused by "jsdom does not fetch <img src>". The real app put an
    // <img src="/api/android/pair/qr.svg"> on screen, the browser's image loader sent
    // no session token, and the server answered 401 — a broken-image icon where the
    // code should be. A test that tolerates a request never being made cannot see that.
    await start();
    expect(calls.some((c) => c === "GET /api/android/pair/qr.svg")).toBe(true);
    expect(document.querySelector('img[src*="/api/"]')).toBeNull();
  });

  it("inlines the returned SVG", async () => {
    await start();
    const holder = screen.getByRole("img", { name: /pairing code/i });
    expect(holder.querySelector("svg")).toBeTruthy();
  });

  it("renders the code big enough for a phone camera, and can go bigger", async () => {
    // The first version constrained the symbol to 230px: about five pixels per module
    // for a 41-module code. A phone camera against a glossy screen could not read it,
    // and the failure was indistinguishable from a network problem — three empty
    // discovery windows before the raw mDNS listener showed the phone never advertised
    // because the scan never completed.
    await start();
    const holder = screen.getByRole("img", { name: /pairing code/i });
    // Rendered at its natural size, NOT stretched: the backend emits an exact integer
    // multiple of the module count, and any other size anti-aliases the module edges.
    expect(holder.className).not.toMatch(/w-\[\d+px\]/);

    // And an enlarge path exists, because "bigger still" is the actual remedy.
    fireEvent.click(screen.getByRole("button", { name: /enlarge the code/i }));
    const overlay = await screen.findByRole("dialog", { name: /pairing code/i });
    expect(overlay.querySelector("svg")).toBeTruthy();
    expect(overlay.innerHTML).toMatch(/min\(78vw,78vh\)/);
  });

  it("closing the enlarged view leaves the session running", async () => {
    await start();
    fireEvent.click(screen.getByRole("button", { name: /enlarge the code/i }));
    const overlay = await screen.findByRole("dialog", { name: /pairing code/i });
    fireEvent.click(overlay);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.some((c) => c === "DELETE /api/android/pair/qr")).toBe(false);
  });

  it("never renders the payload as text", async () => {
    await start();
    expect(document.body.textContent).not.toContain("WIFI:T:ADB");
  });
});

describe("when two phones arrive", () => {
  it("asks which one instead of picking", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /show the pairing code/i }));
    await screen.findByRole("img", { name: /pairing code/i });
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
    await screen.findByRole("img", { name: /pairing code/i });
    session = { ...session, status: "expired", seconds_left: 0 };
    expect(await screen.findByText(/no phone arrived/i, {}, { timeout: 4000 })).toBeTruthy();
    expect(screen.getByText(/never opened on the phone/i)).toBeTruthy();
    expect(screen.getByText(/different network/i)).toBeTruthy();
    expect(screen.getByText(/Windows Firewall/i)).toBeTruthy();
    expect(screen.getByText(/cannot tell these apart/i)).toBeTruthy();
  });
});

describe("a dead end must become a signpost", () => {
  it("names the likely cause and points at the path that does not need mDNS", async () => {
    // Two independent reports now: a home network where the phone answers a ping in
    // 40ms and sends zero mDNS packets in sixty seconds, and a workplace network where
    // client isolation makes multicast blocking the norm. "Expired" on its own turned
    // six attempts into six dead ends; the remedy is one panel away and must be named.
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /show the pairing code/i }));
    await screen.findByRole("img", { name: /pairing code/i });
    session = { ...session, status: "expired", seconds_left: 0, diagnosis: "no_announcement" };

    const cause = await screen.findByText(/does not carry the phone's announcement/i, {}, {
      timeout: 4000,
    });
    expect(cause).toBeTruthy();
    const remedy = screen.getByText(/Pair with a code/i);
    expect(remedy.textContent).toMatch(/works on any network/i);
  });

  it("does not blame the network when the hub has no reason to", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /show the pairing code/i }));
    await screen.findByRole("img", { name: /pairing code/i });
    session = { ...session, status: "failed", error: "adb refused", diagnosis: "" };
    await screen.findByText(/adb refused/i, {}, { timeout: 4000 });
    expect(screen.queryByText(/does not carry the phone's announcement/i)).toBeNull();
  });
});

describe("the credential's lifetime", () => {
  it("hands the paired phone back so nothing is retyped", async () => {
    const onPaired = vi.fn();
    renderPanel(onPaired);
    fireEvent.click(await screen.findByRole("button", { name: /show the pairing code/i }));
    await screen.findByRole("img", { name: /pairing code/i });
    session = { ...session, status: "paired", device: { host: "192.168.3.30", port: 34677 } };
    await waitFor(() => expect(onPaired).toHaveBeenCalledWith("192.168.3.30", 34677), {
      timeout: 4000,
    });
  });

  it("ends the session when the panel goes away", async () => {
    const view = renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /show the pairing code/i }));
    await screen.findByRole("img", { name: /pairing code/i });
    view.unmount();
    await waitFor(() =>
      expect(calls.some((c) => c === "DELETE /api/android/pair/qr")).toBe(true),
    );
  });

  it("ends it on the close button too", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /show the pairing code/i }));
    await screen.findByRole("img", { name: /pairing code/i });
    fireEvent.click(screen.getByRole("button", { name: /close pairing/i }));
    await waitFor(() =>
      expect(calls.some((c) => c === "DELETE /api/android/pair/qr")).toBe(true),
    );
  });
});

// The half that makes scanning enough: the hub sweeps the phone the operator picked, so
// the pick has to actually reach the server. An unsent field is exactly the class of bug
// that made the code invisible once already (an <img src> that could not authenticate).
describe("picking the phone is what makes it automatic", () => {
  async function pickGalaxy() {
    // Wait for the option itself: the list arrives from the app's own network scan, and
    // setting a select to a value it does not have yet silently leaves it empty.
    await screen.findByRole("option", { name: /Galaxy/i });
    const picker = screen.getByLabelText(/pick your phone/i) as HTMLSelectElement;
    fireEvent.change(picker, { target: { value: "192.168.3.24" } });
    expect(picker.value).toBe("192.168.3.24");
    return picker;
  }

  it("sends the picked address when the session starts", async () => {
    renderPanel();
    await pickGalaxy();
    fireEvent.click(screen.getByRole("button", { name: /show the pairing code/i }));

    await waitFor(() =>
      expect(bodies.some((b) => JSON.parse(b).host === "192.168.3.24")).toBe(true),
    );
  });

  it("offers phones to pick but not devices already added", async () => {
    renderPanel();
    await pickGalaxy();
    const labels = [...(screen.getByLabelText(/pick your phone/i) as HTMLSelectElement).options]
      .map((o) => o.textContent ?? "");
    expect(labels.some((l) => l.includes("Printer"))).toBe(false);
  });

  it("says which of the two routes is in play, instead of leaving it to be discovered", async () => {
    renderPanel();
    await pickGalaxy();
    fireEvent.click(screen.getByRole("button", { name: /show the pairing code/i }));
    expect(await screen.findByText(/added automatically/i)).toBeTruthy();
  });

  it("does not promise an automatic result when no phone was picked", async () => {
    // Over-claiming here is what wasted six real sessions: the panel implied scanning was
    // enough while it was in fact waiting on an announcement this network does not carry.
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /show the pairing code/i }));
    expect(await screen.findByText(/wait for an announcement/i)).toBeTruthy();
  });
});
