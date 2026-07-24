import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "@/lib/language";
import { ThemeProvider } from "@/lib/theme";
import i18n from "@/i18n";
import { UpdatesPage } from "./UpdatesPage";

// The in-app Updates page (Windows tab by default). It loads system info from
// GET /api/system/info and the pending/installed update list from
// GET /api/updates/{windows|drivers}. "Check for updates" POSTs to
// /api/updates/windows/check; installs POST to .../install; live progress is
// polled from .../status. The backend is fetch-mocked with realistic shapes.

interface UpdateRow {
  id: number;
  update_id: string;
  title: string;
  description: string;
  kb_articles: string[];
  categories: string[];
  severity: string;
  size_mb: number;
  is_downloaded: boolean;
  requires_reboot: boolean;
  is_installed: boolean;
  install_result: number;
  release_date: string;
  last_checked: string | null;
}

interface UpdatesList {
  pending: UpdateRow[];
  installed_recent: UpdateRow[];
  total_pending: number;
  total_size_mb: number;
  last_checked: string | null;
}

function makeUpdate(over: Partial<UpdateRow> = {}): UpdateRow {
  return {
    id: 1,
    update_id: "UID-1",
    title: "Security Update for Windows",
    description: "",
    kb_articles: ["KB5000001"],
    categories: ["Security Updates"],
    severity: "Critical",
    size_mb: 42.5,
    is_downloaded: false,
    requires_reboot: true,
    is_installed: false,
    install_result: 0,
    release_date: "2026-07-01",
    last_checked: "2026-07-20T10:00:00Z",
    ...over,
  };
}

let windowsList: UpdatesList;
let driversList: UpdatesList;
let sysInfo: Record<string, unknown> | null;
let checkShouldFail: boolean;
let checkCalls: number;

function res(status: number, body: unknown, ok = status < 400): Response {
  return { ok, status, json: async () => body } as unknown as Response;
}

function router(url: RequestInfo | URL, _init?: RequestInit): Promise<Response> {
  const u = String(url);

  if (u.includes("/api/system/info")) {
    return Promise.resolve(sysInfo ? res(200, sysInfo) : res(404, {}));
  }
  if (u.includes("/api/system/reboot")) {
    return Promise.resolve(res(200, { status: "scheduled", delay_seconds: 60 }));
  }
  if (u.includes("/api/updates/windows/check")) {
    checkCalls += 1;
    if (checkShouldFail) return Promise.resolve(res(500, { error: "service busy" }));
    return Promise.resolve(res(200, {}));
  }
  if (u.includes("/api/updates/windows/install")) {
    return Promise.resolve(
      res(200, { installed: 1, total: 1, reboot_required: true, results: [] }),
    );
  }
  if (u.includes("/api/updates/windows/status")) {
    return Promise.resolve(
      res(200, {
        is_running: false,
        operation: "",
        phase: "idle",
        total: 0,
        completed: 0,
        elapsed_seconds: 0,
        last_message: "",
        error: null,
        log: [],
      }),
    );
  }
  if (u.includes("/api/updates/drivers")) {
    return Promise.resolve(res(200, driversList));
  }
  if (u.includes("/api/updates/windows")) {
    return Promise.resolve(res(200, windowsList));
  }
  return Promise.resolve(res(200, {}));
}

function renderPage(props: Partial<Parameters<typeof UpdatesPage>[0]> = {}) {
  vi.stubGlobal("fetch", vi.fn(router));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <LanguageProvider>
          <UpdatesPage onBack={() => {}} {...props} />
        </LanguageProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const emptyList: UpdatesList = {
  pending: [],
  installed_recent: [],
  total_pending: 0,
  total_size_mb: 0,
  last_checked: null,
};

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
  windowsList = { ...emptyList };
  driversList = { ...emptyList };
  sysInfo = null;
  checkShouldFail = false;
  checkCalls = 0;
  localStorage.clear();
  localStorage.setItem("homeupdater.language", "en");
});

afterEach(async () => {
  cleanup();
  vi.restoreAllMocks();
  await i18n.changeLanguage("en");
});

describe("UpdatesPage", () => {
  it("renders the title and the update-source tabs", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "Updates" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Windows updates" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Software (winget)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Device drivers" })).toBeInTheDocument();
  });

  it("shows the empty state when there are no pending updates", async () => {
    renderPage();
    expect(await screen.findByText("No pending updates")).toBeInTheDocument();
    expect(
      screen.getByText(/Click .*Check for updates.* to see what's available/),
    ).toBeInTheDocument();
  });

  it("loads pending updates and renders a row plus the This PC card", async () => {
    windowsList = {
      pending: [makeUpdate({ update_id: "UID-9", title: "Cumulative Update for Windows 11" })],
      installed_recent: [],
      total_pending: 1,
      total_size_mb: 42.5,
      last_checked: "2026-07-20T10:00:00Z",
    };
    sysInfo = { hostname: "HOME-PC", user: "mohanad", system: "Windows", release: "11", machine: "x64" };
    renderPage();
    expect(await screen.findByText("Cumulative Update for Windows 11")).toBeInTheDocument();
    expect(await screen.findByText("This PC")).toBeInTheDocument();
    expect(screen.getByText("HOME-PC")).toBeInTheDocument();
  });

  it("switches to the drivers tab and loads driver updates", async () => {
    driversList = {
      pending: [makeUpdate({ update_id: "DRV-1", title: "Intel Graphics Driver Update" })],
      installed_recent: [],
      total_pending: 1,
      total_size_mb: 12,
      last_checked: "2026-07-20T10:00:00Z",
    };
    renderPage();
    // Wait for the initial (empty) Windows tab to settle, then switch tabs.
    await screen.findByText("No pending updates");
    fireEvent.click(screen.getByRole("button", { name: "Device drivers" }));
    expect(await screen.findByText("Intel Graphics Driver Update")).toBeInTheDocument();
  });

  it("shows a friendly error when the update check fails", async () => {
    windowsList = {
      pending: [makeUpdate({ update_id: "UID-2", title: "Defender Definition Update" })],
      installed_recent: [],
      total_pending: 1,
      total_size_mb: 5,
      last_checked: "2026-07-20T10:00:00Z",
    };
    checkShouldFail = true;
    renderPage();
    await screen.findByText("Defender Definition Update");
    fireEvent.click(screen.getByRole("button", { name: /Check for updates/ }));
    expect(await screen.findByText("Update check failed")).toBeInTheDocument();
    expect(checkCalls).toBeGreaterThan(0);
  });

  it("calls onBack when the Dashboard button is clicked", async () => {
    const onBack = vi.fn();
    renderPage({ onBack });
    await screen.findByRole("heading", { name: "Updates" });
    fireEvent.click(screen.getByRole("button", { name: /Dashboard/ }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
