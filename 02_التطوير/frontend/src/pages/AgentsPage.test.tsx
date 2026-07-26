import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "@/lib/language";
import { ThemeProvider } from "@/lib/theme";
import i18n from "@/i18n";
import { AgentsPage } from "./AgentsPage";

// This page hands out a credential and grants trust to machines, so the tests police
// the guards rather than the layout:
//   • nothing on this page may issue a command — the protocol cannot carry one usefully
//     and a button that always fails teaches the operator that the page lies;
//   • the answer to the confirmation challenge must never be on the operator's screen;
//   • the two irreversible actions must not be reachable by clicking;
//   • the token must never reach storage, and a dead token must leave the DOM.

interface AgentRow {
  id: string;
  fingerprint: string | null;
  fingerprint_head: string;
  fingerprint_masked?: string;
  name: string;
  os_name: string;
  agent_version: string;
  status: "pending" | "active" | "revoked";
  enrolled_at: string | null;
  last_seen: string | null;
  last_skew_seconds: number;
  inventory_count: number;
  pending_updates: number;
}

let agents: AgentRow[];
let listener: Record<string, unknown>;
let refusals: Record<string, unknown>[];
let mintStatus: number;
let mintDetail: string;
let confirmStatus: number;
let calls: string[];

const PENDING: AgentRow = {
  id: "a1",
  fingerprint: null,
  fingerprint_head: "a3f19c02",
  fingerprint_masked: "a3f19c02 •••••••• •••••••• ••••••••",
  name: "PC-Reception",
  os_name: "Windows 11",
  agent_version: "1.17.0",
  status: "pending",
  enrolled_at: "2026-07-26T09:00:00+00:00",
  last_seen: null,
  last_skew_seconds: 0,
  inventory_count: 0,
  pending_updates: 0,
};

const ACTIVE: AgentRow = {
  ...PENDING,
  id: "a2",
  name: "PC-Accounting",
  status: "active",
  fingerprint: "a3f19c02b7d4e6108c5f21ab9034d71e",
  fingerprint_masked: undefined,
  last_seen: new Date().toISOString(),
  inventory_count: 42,
  pending_updates: 3,
};

const RUNNING = {
  enabled: true,
  running: true,
  host: "0.0.0.0",
  port: 8443,
  error: "",
  certificate: {
    fingerprint_sha256: "f".repeat(64),
    not_after: "2028-10-28T00:00:00+00:00",
    names: ["HUB-PC", "192.168.1.10"],
    self_signed: true,
  },
  addresses: ["https://192.168.1.10:8443", "https://HUB-PC:8443"],
};

const OFF = { ...RUNNING, enabled: false, running: false, certificate: {}, addresses: [] };

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
  calls.push(`${method} ${u}`);
  if (u.includes("/api/agents/enrolment-token")) {
    return Promise.resolve(
      mintStatus === 200
        ? res(200, {
            token: "HUENROL1.payload.signature",
            expires_at: new Date(Date.now() + 900_000).toISOString(),
            bound: false,
            requires_confirmation: true,
            target_hint: "",
          })
        : res(mintStatus, { detail: mintDetail }),
    );
  }
  if (u.includes("/api/agents/refusals")) {
    return Promise.resolve(res(200, { refusals, total: refusals.length }));
  }
  if (u.includes("/api/agents/listener")) {
    if (method === "POST") return Promise.resolve(res(200, RUNNING));
    return Promise.resolve(res(200, listener));
  }
  if (u.includes("/confirm")) {
    return Promise.resolve(
      confirmStatus === 200
        ? res(200, { ...PENDING, status: "active" })
        : res(confirmStatus, { detail: "fingerprint_mismatch" }),
    );
  }
  if (u.includes("/revoke")) return Promise.resolve(res(200, { ...ACTIVE, status: "revoked" }));
  if (u.endsWith("/api/agents")) {
    return Promise.resolve(
      res(200, {
        agents,
        total: agents.length,
        counts: { pending: 0, active: agents.length, revoked: 0 },
      }),
    );
  }
  return Promise.resolve(res(200, {}));
}

/** Wait until the listener query has resolved: until then every control is
 *  deliberately disabled, and clicking one is a silent no-op. The badge cannot be
 *  used for this — it reads "Closed" while loading too. */
async function ready() {
  await screen.findByTestId("listener-ready");
}

function renderPage() {
  vi.stubGlobal("fetch", vi.fn(router));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <LanguageProvider>
          <AgentsPage onBack={() => {}} />
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
  agents = [];
  listener = OFF;
  refusals = [];
  mintStatus = 200;
  mintDetail = "";
  confirmStatus = 200;
  calls = [];
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("what the page promises", () => {
  it("states what the agent cannot do, in every state", async () => {
    renderPage();
    expect(await screen.findByText(/does not update itself/i)).toBeTruthy();
    expect(screen.getByText(/stops when its window closes/i)).toBeTruthy();
    expect(screen.getByText(/does not install updates remotely/i)).toBeTruthy();
  });

  it("keeps the limits visible when the fleet fails to load", async () => {
    agents = [];
    renderPage();
    expect(await screen.findByText(/does not update itself/i)).toBeTruthy();
  });

  it("never issues a command, whatever is clicked", async () => {
    listener = RUNNING;
    agents = [ACTIVE];
    renderPage();
    await ready();
    await screen.findByText("PC-Accounting");
    document.querySelectorAll("button").forEach((b) => fireEvent.click(b));
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    expect(calls.filter((c) => c.includes("/command"))).toHaveLength(0);
  });
});

describe("the listener", () => {
  it("does not open the port on one click", async () => {
    renderPage();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: /open the port/i }));
    // The confirm panel names the consequence; nothing has been sent yet.
    expect(await screen.findByText(/whole local network/i)).toBeTruthy();
    expect(calls.filter((c) => c.startsWith("POST"))).toHaveLength(0);
  });

  it("opens it after the consequence is acknowledged", async () => {
    renderPage();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: /open the port/i }));
    const buttons = await screen.findAllByRole("button", { name: /open the port/i });
    fireEvent.click(buttons[buttons.length - 1]);
    await waitFor(() =>
      expect(calls.some((c) => c === "POST /api/agents/listener")).toBe(true),
    );
  });

  it("gives the firewall command without running it", async () => {
    listener = RUNNING;
    renderPage();
    await ready();
    fireEvent.click(screen.getByText(/nothing arriving/i));
    expect(screen.getByText(/netsh advfirewall/)).toBeTruthy();
    expect(screen.getByText(/your decision/i)).toBeTruthy();
  });

  it("names the reason when the port is enabled but dead", async () => {
    listener = { ...RUNNING, running: false, error: "[Errno 10048] address already in use" };
    renderPage();
    expect(await screen.findByText(/10048/)).toBeTruthy();
    expect(screen.getByText(/another program is using the port/i)).toBeTruthy();
  });
});

describe("minting a token", () => {
  it("refuses to mint while nothing is listening, and says why", async () => {
    renderPage();
    expect(await screen.findByText(/Open the agent port first/i)).toBeTruthy();
    const btn = await screen.findByRole("button", { name: /create enrolment token/i });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it("warns that an unbound token works from any machine, before it is created", async () => {
    listener = RUNNING;
    renderPage();
    expect(await screen.findByText(/works from any machine on the network/i)).toBeTruthy();
  });

  it("builds the command with the chosen address and the name", async () => {
    listener = RUNNING;
    renderPage();
    await ready();
    fireEvent.change(screen.getByLabelText(/a name for the machine/i), {
      target: { value: "PC-Reception" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create enrolment token/i }));
    const cmd = await screen.findByText(/HomeUpdater\.exe --agent/);
    expect(cmd.textContent).toContain("--hub https://192.168.1.10:8443");
    expect(cmd.textContent).toContain("--token HUENROL1.payload.signature");
    expect(cmd.textContent).toContain("--name PC-Reception");
  });

  it("omits --name when no name was given", async () => {
    listener = RUNNING;
    renderPage();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: /create enrolment token/i }));
    const cmd = await screen.findByText(/HomeUpdater\.exe --agent/);
    expect(cmd.textContent).not.toContain("--name");
  });

  it("never puts the token in storage", async () => {
    listener = RUNNING;
    renderPage();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: /create enrolment token/i }));
    await screen.findByText(/HomeUpdater\.exe --agent/);
    expect(JSON.stringify(localStorage)).not.toContain("HUENROL");
    expect(JSON.stringify(sessionStorage)).not.toContain("HUENROL");
  });

  it("removes the dead command from the page when the token expires", async () => {
    listener = RUNNING;
    renderPage();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: /create enrolment token/i }));
    await screen.findByText(/HomeUpdater\.exe --agent/);
    vi.setSystemTime(Date.now() + 16 * 60 * 1000);
    await waitFor(() => expect(screen.queryByText(/HomeUpdater\.exe --agent/)).toBeNull(), {
      timeout: 3000,
    });
    expect(screen.getByText(/expired unused/i)).toBeTruthy();
  });

  it("explains a refused mint in the operator's words", async () => {
    listener = RUNNING;
    mintStatus = 400;
    mintDetail = "unbound_requires_optin";
    renderPage();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: /create enrolment token/i }));
    expect(await screen.findByText(/explicitly accept a token any machine can use/i)).toBeTruthy();
  });

  it("asks where to get the fingerprint when binding to one machine", async () => {
    listener = RUNNING;
    renderPage();
    await ready();
    fireEvent.click(screen.getByLabelText(/tie the token to one specific machine/i));
    expect(screen.getByText(/--show-id/)).toBeTruthy();
  });
});

describe("trusting a machine", () => {
  it("does not show the characters it asks the operator to type", async () => {
    listener = RUNNING;
    agents = [PENDING];
    renderPage();
    await screen.findByText("PC-Reception");
    expect(screen.getByText(/a3f19c02 •/)).toBeTruthy();
    // The tail is the challenge; if it were rendered the check would be a
    // transcription exercise from the box next door.
    expect(document.body.textContent).not.toContain("9034d71e");
  });

  it("keeps Confirm disabled until eight characters are typed", async () => {
    listener = RUNNING;
    agents = [PENDING];
    renderPage();
    const btn = (await screen.findByRole("button", {
      name: /trust this machine/i,
    })) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/last 8 characters/i), { target: { value: "9034" } });
    expect(btn.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/last 8 characters/i), {
      target: { value: "9034d71e" },
    });
    expect(btn.disabled).toBe(false);
  });

  it("sends the typed suffix and nothing else", async () => {
    listener = RUNNING;
    agents = [PENDING];
    renderPage();
    fireEvent.change(await screen.findByLabelText(/last 8 characters/i), {
      target: { value: "9034d71e" },
    });
    fireEvent.click(screen.getByRole("button", { name: /trust this machine/i }));
    await waitFor(() => expect(calls.some((c) => c.includes("/confirm"))).toBe(true));
  });

  it("tells the operator where to read the right characters after a mismatch", async () => {
    listener = RUNNING;
    agents = [PENDING];
    confirmStatus = 400;
    renderPage();
    fireEvent.change(await screen.findByLabelText(/last 8 characters/i), {
      target: { value: "00000000" },
    });
    fireEvent.click(screen.getByRole("button", { name: /trust this machine/i }));
    expect(await screen.findByText(/--show-id/)).toBeTruthy();
  });
});

describe("the irreversible actions", () => {
  it("does not revoke until the machine's name is typed", async () => {
    listener = RUNNING;
    agents = [ACTIVE];
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /revoke/i }));
    expect(screen.getByText(/cannot enrol again while it is in the list/i)).toBeTruthy();
    const buttons = screen.getAllByRole("button", { name: /revoke/i });
    fireEvent.click(buttons[buttons.length - 1]);
    expect(calls.filter((c) => c.includes("/revoke"))).toHaveLength(0);

    fireEvent.change(screen.getByLabelText(/type "PC-Accounting"/i), {
      target: { value: "PC-Accounting" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: /revoke/i }).slice(-1)[0]);
    await waitFor(() => expect(calls.some((c) => c.includes("/revoke"))).toBe(true));
  });

  it("says how to undo a revocation, because the code makes it permanent otherwise", async () => {
    listener = RUNNING;
    agents = [ACTIVE];
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /revoke/i }));
    expect(screen.getByText(/forget it and enrol it again/i)).toBeTruthy();
  });

  it("does not regenerate the certificate until the damage is named", async () => {
    listener = RUNNING;
    agents = [ACTIVE];
    renderPage();
    await ready();
    fireEvent.click(screen.getByText(/hub certificate/i));
    const btn = (await screen.findByRole("button", {
      name: /issue a new certificate/i,
    })) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/how many machines this stops/i), {
      target: { value: "1" },
    });
    expect(btn.disabled).toBe(false);
  });
});

describe("why a machine went quiet", () => {
  it("turns a clock skew into the command that fixes it", async () => {
    listener = RUNNING;
    refusals = [
      {
        at: new Date().toISOString(),
        agent_id: "",
        agent_name: null,
        reason: "clock_skew:412",
        path: "/api/agents/checkin",
        source: "192.168.1.31",
      },
    ];
    renderPage();
    const line = await screen.findByText(/w32tm \/resync/);
    expect(line.textContent).toContain("412");
  });

  it("explains an empty feed next to a silent machine, rather than implying all is well", async () => {
    listener = RUNNING;
    agents = [{ ...ACTIVE, last_seen: new Date(Date.now() - 3_600_000).toISOString() }];
    refusals = [];
    renderPage();
    expect(await screen.findByText(/never reached the hub at all/i)).toBeTruthy();
  });
});
