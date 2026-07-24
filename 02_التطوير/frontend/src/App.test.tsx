import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "@/lib/language";
import { ThemeProvider } from "@/lib/theme";
import i18n from "@/i18n";
import App from "./App";

// The post-upgrade toast: shown once when the backend reports the version went
// up, then suppressed per-version via localStorage. Backend is fetch-mocked.

let upgradeNotice: { upgraded: boolean; previous: string | null; current: string | null };

function res(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response;
}

function router(url: RequestInfo | URL): Promise<Response> {
  const u = String(url);
  if (u.includes("/api/system/health"))
    return Promise.resolve(res({ status: "healthy", service: "HomeUpdater", version: "1.4.7", build_mode: "release" }));
  if (u.includes("/api/system/version"))
    return Promise.resolve(res({ app: "HomeUpdater", version: "1.4.7", build: "release" }));
  if (u.includes("/api/system/update-check"))
    return Promise.resolve(res({ current: "1.4.7", latest: null, update_available: false, url: null, checked: false }));
  if (u.includes("/api/system/upgrade-notice")) return Promise.resolve(res(upgradeNotice));
  if (u.includes("/api/devices/stats")) return Promise.resolve(res({ total: 0, online: 0 }));
  if (u.includes("/api/devices")) return Promise.resolve(res({ devices: [], total: 0 }));
  return Promise.resolve(res({}));
}

function renderApp() {
  vi.stubGlobal("fetch", vi.fn(router));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <LanguageProvider>
          <App />
        </LanguageProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const sawUpgradeCheck = () =>
  waitFor(() =>
    expect(
      (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.some((c) =>
        String(c[0]).includes("/api/system/upgrade-notice"),
      ),
    ).toBe(true),
  );

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
  upgradeNotice = { upgraded: false, previous: null, current: null };
  localStorage.clear();
  localStorage.setItem("homeupdater.language", "en");
  localStorage.setItem("hu_onboarding_v1", "done"); // keep the first-run tour out of the way
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("App post-upgrade toast", () => {
  it("shows 'upgraded from X to Y' when the backend reports an upgrade", async () => {
    upgradeNotice = { upgraded: true, previous: "1.4.6", current: "1.4.7" };
    renderApp();
    expect(await screen.findByText("Updated from 1.4.6 to 1.4.7")).toBeInTheDocument();
  });

  it("suppresses the toast when it was already seen for that version", async () => {
    upgradeNotice = { upgraded: true, previous: "1.4.6", current: "1.4.7" };
    localStorage.setItem("hu_upgrade_seen_1.4.7", "1");
    renderApp();
    await sawUpgradeCheck();
    expect(screen.queryByText("Updated from 1.4.6 to 1.4.7")).not.toBeInTheDocument();
  });

  it("shows nothing when there was no upgrade", async () => {
    upgradeNotice = { upgraded: false, previous: null, current: "1.4.7" };
    renderApp();
    await sawUpgradeCheck();
    expect(screen.queryByText(/Updated from/)).not.toBeInTheDocument();
  });
});
