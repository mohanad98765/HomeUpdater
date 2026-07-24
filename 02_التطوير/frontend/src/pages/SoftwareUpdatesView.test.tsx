import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "@/lib/language";
import { ThemeProvider } from "@/lib/theme";
import i18n from "@/i18n";
import { SoftwareUpdatesView } from "./SoftwareUpdatesView";

// The embedded winget (software) updates view: loads pending packages from
// GET /api/updates/software, checks via POST .../check, installs via
// POST .../install, and polls GET /api/updates/windows/status while a
// mutation runs. Backend is fetch-mocked with realistic shapes.

interface PackageRow {
  id: number;
  package_id: string;
  name: string;
  current_version: string;
  available_version: string;
  source: string;
  size_mb: number;
  is_installed: boolean;
  install_result: number;
  last_checked: string | null;
}
interface PackagesList {
  pending: PackageRow[];
  total_pending: number;
  last_checked: string | null;
}

function pkg(over: Partial<PackageRow> = {}): PackageRow {
  return {
    id: 1,
    package_id: "Mozilla.Firefox",
    name: "Mozilla Firefox",
    current_version: "120.0",
    available_version: "121.0",
    source: "winget",
    size_mb: 55,
    is_installed: false,
    install_result: 0,
    last_checked: "2026-07-20T10:00:00Z",
    ...over,
  };
}

let packagesList: PackagesList;
let checkFails: boolean;

function res(status: number, body: unknown, ok = status < 400): Response {
  return { ok, status, json: async () => body } as unknown as Response;
}

function router(url: RequestInfo | URL, _init?: RequestInit): Promise<Response> {
  const u = String(url);
  if (u.includes("/api/updates/software/check")) {
    if (checkFails) return Promise.resolve(res(500, { error: "winget offline" }));
    // A successful check surfaces a freshly discovered pending package.
    packagesList = {
      pending: [pkg()],
      total_pending: 1,
      last_checked: "2026-07-23T12:00:00Z",
    };
    return Promise.resolve(res(200, {}));
  }
  if (u.includes("/api/updates/software/install")) {
    const installed = packagesList.pending.length;
    packagesList = { pending: [], total_pending: 0, last_checked: packagesList.last_checked };
    return Promise.resolve(
      res(200, {
        installed,
        total: installed,
        results: [],
      }),
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
  if (u.includes("/api/updates/software")) {
    return Promise.resolve(res(200, packagesList));
  }
  return Promise.resolve(res(200, {}));
}

function renderView() {
  vi.stubGlobal("fetch", vi.fn(router));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <LanguageProvider>
          <SoftwareUpdatesView />
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
  packagesList = { pending: [], total_pending: 0, last_checked: null };
  checkFails = false;
  localStorage.clear();
  localStorage.setItem("homeupdater.language", "en");
});

afterEach(async () => {
  cleanup();
  vi.restoreAllMocks();
  await i18n.changeLanguage("en");
});

describe("SoftwareUpdatesView", () => {
  it("renders the header title and last-checked label", () => {
    renderView();
    expect(screen.getByRole("heading", { name: "Software updates" })).toBeInTheDocument();
    expect(screen.getByText(/Last checked/)).toBeInTheDocument();
  });

  it("shows the empty state when nothing is pending", async () => {
    renderView();
    expect(await screen.findByText("No pending updates")).toBeInTheDocument();
    expect(screen.getByText("Click Check to query winget for app upgrades")).toBeInTheDocument();
  });

  it("loads pending packages and renders a row", async () => {
    packagesList = { pending: [pkg()], total_pending: 1, last_checked: "2026-07-20T10:00:00Z" };
    renderView();
    expect(await screen.findByText("Mozilla Firefox")).toBeInTheDocument();
    expect(screen.getByText("Mozilla.Firefox")).toBeInTheDocument();
    expect(screen.getByText("121.0")).toBeInTheDocument();
    // Column headers from the winget table.
    expect(screen.getByText("Available")).toBeInTheDocument();
  });

  it("checks for updates and surfaces the newly found package", async () => {
    renderView();
    await screen.findByText("No pending updates");
    // Empty state renders both a header and a CTA "Check for updates" button.
    fireEvent.click(screen.getAllByRole("button", { name: /Check for updates/ })[0]);
    expect(await screen.findByText("Mozilla Firefox")).toBeInTheDocument();
  });

  it("installs pending packages after confirmation and shows a success summary", async () => {
    packagesList = { pending: [pkg()], total_pending: 1, last_checked: "2026-07-20T10:00:00Z" };
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderView();
    await screen.findByText("Mozilla Firefox");
    fireEvent.click(screen.getByRole("button", { name: /Install all/ }));
    expect(confirmSpy).toHaveBeenCalled();
    expect(await screen.findByText("Installed 1/1 successfully")).toBeInTheDocument();
  });

  it("shows a friendly error with a retry when the check fails", async () => {
    checkFails = true;
    renderView();
    await screen.findByText("No pending updates");
    fireEvent.click(screen.getAllByRole("button", { name: /Check for updates/ })[0]);
    expect(await screen.findByText("Update check failed")).toBeInTheDocument();
    expect(screen.getByText(/The update service may be briefly busy/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Retry/ })).toBeInTheDocument();
  });
});
