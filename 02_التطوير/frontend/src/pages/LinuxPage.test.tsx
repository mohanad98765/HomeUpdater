import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "@/lib/language";
import { ThemeProvider } from "@/lib/theme";
import i18n from "@/i18n";
import { LinuxPage } from "./LinuxPage";

// Linux / SSH page: lists SSH hosts from GET /api/ssh/hosts, adds via POST,
// checks updates via POST /api/ssh/hosts/:id/check, upgrades and deletes.
// The backend is fetch-mocked; each test seeds the mutable state below.

interface SSHHost {
  id: number;
  host: string;
  port: number;
  username: string;
  custom_name: string;
  os_name: string;
  pkg_manager: string;
  is_online: boolean;
  host_key_verified: boolean;
  display_name: string;
}
interface UpdateCheck {
  total: number;
  packages: { name: string; current: string; available: string }[];
}

let hostsList: SSHHost[];
let checkResult: UpdateCheck;
let checkFail: boolean;
let lastAdd: Record<string, unknown> | null;

function host(over: Partial<SSHHost> = {}): SSHHost {
  return {
    id: 1,
    host: "192.168.1.50",
    port: 22,
    username: "pi",
    custom_name: "",
    os_name: "Ubuntu 22.04",
    pkg_manager: "apt",
    is_online: true,
    host_key_verified: true,
    display_name: "Raspberry Pi",
    ...over,
  };
}

function res(status: number, body: unknown, ok = status < 400): Response {
  return { ok, status, json: async () => body } as unknown as Response;
}

function router(url: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const u = String(url);
  const method = init?.method ?? "GET";
  if (u.includes("/check")) {
    if (checkFail) return Promise.resolve(res(500, { detail: "SSH connection refused" }));
    return Promise.resolve(res(200, checkResult));
  }
  if (u.includes("/upgrade")) {
    return Promise.resolve(res(200, {}));
  }
  if (u.includes("/api/ssh/hosts")) {
    if (method === "POST") {
      lastAdd = JSON.parse(String(init!.body));
      return Promise.resolve(res(200, { ok: true }));
    }
    if (method === "DELETE") {
      return Promise.resolve(res(200, { ok: true }));
    }
    return Promise.resolve(res(200, { hosts: hostsList, total: hostsList.length }));
  }
  return Promise.resolve(res(200, {}));
}

function renderPage(props: Partial<Parameters<typeof LinuxPage>[0]> = {}) {
  vi.stubGlobal("fetch", vi.fn(router));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <LanguageProvider>
          <LinuxPage onBack={() => {}} {...props} />
        </LanguageProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

beforeAll(async () => {
  // jsdom has no matchMedia; ThemeProvider reads it for the system theme.
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
  hostsList = [];
  checkResult = { total: 0, packages: [] };
  checkFail = false;
  lastAdd = null;
  localStorage.clear();
  localStorage.setItem("homeupdater.language", "en");
});

afterEach(async () => {
  cleanup();
  vi.restoreAllMocks();
  await i18n.changeLanguage("en");
});

describe("LinuxPage", () => {
  it("renders the page title and add button", async () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Linux / SSH" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Add device/ })).toBeInTheDocument();
  });

  it("shows the empty state when there are no hosts", async () => {
    renderPage();
    expect(
      await screen.findByText(/No Linux devices\. Add one over SSH/),
    ).toBeInTheDocument();
  });

  it("loads hosts and renders a device row", async () => {
    hostsList = [host()];
    renderPage();
    expect(await screen.findByText("Raspberry Pi")).toBeInTheDocument();
    // detail line: os · user@host:port · pkg_manager
    expect(screen.getByText(/pi@192\.168\.1\.50:22/)).toBeInTheDocument();
  });

  it("opens the add form and posts a new host", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /Add device/ }));

    expect(
      screen.getByRole("heading", { name: "New Linux device (SSH)" }),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("IP address (e.g. 192.168.1.50)"), {
      target: { value: "10.0.0.5" },
    });
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "root" } });

    const saveBtn = screen.getByRole("button", { name: /Connect & save/ });
    expect(saveBtn).not.toBeDisabled();
    fireEvent.click(saveBtn);

    await vi.waitFor(() => expect(lastAdd).not.toBeNull());
    expect(lastAdd).toMatchObject({ host: "10.0.0.5", username: "root", port: 22 });
  });

  it("keeps Connect & save disabled until host and username are filled", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /Add device/ }));
    expect(screen.getByRole("button", { name: /Connect & save/ })).toBeDisabled();
  });

  it("checks updates and lists upgradable packages", async () => {
    hostsList = [host()];
    checkResult = {
      total: 2,
      packages: [
        { name: "openssl", current: "3.0.1", available: "3.0.2" },
        { name: "curl", current: "7.81.0", available: "7.81.1" },
      ],
    };
    renderPage();
    await screen.findByText("Raspberry Pi");

    fireEvent.click(screen.getByRole("button", { name: /Check updates/ }));

    expect(await screen.findByText(/2 package\(s\) can be upgraded/)).toBeInTheDocument();
    expect(screen.getByText("openssl")).toBeInTheDocument();
    expect(screen.getByText("curl")).toBeInTheDocument();
  });

  it("shows the up-to-date message when no updates are available", async () => {
    hostsList = [host()];
    checkResult = { total: 0, packages: [] };
    renderPage();
    await screen.findByText("Raspberry Pi");

    fireEvent.click(screen.getByRole("button", { name: /Check updates/ }));
    expect(await screen.findByText(/System is up to date/)).toBeInTheDocument();
  });

  it("surfaces a check error", async () => {
    hostsList = [host()];
    checkFail = true;
    renderPage();
    await screen.findByText("Raspberry Pi");

    fireEvent.click(screen.getByRole("button", { name: /Check updates/ }));
    expect(await screen.findByText("SSH connection refused")).toBeInTheDocument();
  });

  it("calls onBack from the dashboard button", async () => {
    const onBack = vi.fn();
    renderPage({ onBack });
    fireEvent.click(screen.getByRole("button", { name: /Dashboard/ }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
