import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "@/lib/language";
import { ThemeProvider } from "@/lib/theme";
import i18n from "@/i18n";
import { HomeAssistantPage } from "./HomeAssistantPage";

// Home Assistant page: reads GET /api/homeassistant/status, saves connection via
// POST /api/homeassistant/config, and (once connected) lists GET /api/homeassistant/updates
// and installs via POST /api/homeassistant/updates/install. Backend is fetch-mocked.

interface HAStatus {
  configured: boolean;
  enabled: boolean;
  connected: boolean;
  base_url?: string;
  has_token?: boolean;
  version?: string;
  location_name?: string;
  error?: string;
}
interface HAUpdate {
  entity_id: string;
  title: string;
  installed_version: string | null;
  latest_version: string | null;
  update_available: boolean;
  release_url: string | null;
}
interface HAUpdates {
  total: number;
  available: HAUpdate[];
  up_to_date: number;
}

let haStatus: HAStatus;
let haUpdates: HAUpdates;
let updatesShouldFail: boolean;
let lastConfigPost: Record<string, unknown> | null;
let lastInstallPost: Record<string, unknown> | null;

function res(status: number, body: unknown, ok = status < 400): Response {
  return { ok, status, json: async () => body } as unknown as Response;
}

function router(url: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const u = String(url);
  const method = init?.method ?? "GET";
  if (u.includes("/api/homeassistant/status")) {
    return Promise.resolve(res(200, haStatus));
  }
  if (u.includes("/api/homeassistant/config") && method === "POST") {
    lastConfigPost = JSON.parse(String(init!.body));
    return Promise.resolve(res(200, { ok: true }));
  }
  if (u.includes("/api/homeassistant/updates/install") && method === "POST") {
    lastInstallPost = JSON.parse(String(init!.body));
    return Promise.resolve(res(200, { ok: true }));
  }
  if (u.includes("/api/homeassistant/updates")) {
    if (updatesShouldFail) return Promise.resolve(res(500, { error: "boom" }));
    return Promise.resolve(res(200, haUpdates));
  }
  return Promise.resolve(res(200, {}));
}

function renderPage(props: Partial<Parameters<typeof HomeAssistantPage>[0]> = {}) {
  vi.stubGlobal("fetch", vi.fn(router));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <LanguageProvider>
          <HomeAssistantPage onBack={() => {}} {...props} />
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
  haStatus = { configured: false, enabled: false, connected: false, has_token: false };
  haUpdates = {
    total: 3,
    up_to_date: 2,
    available: [
      {
        entity_id: "update.living_room_bulb",
        title: "Living Room Bulb",
        installed_version: "1.0.0",
        latest_version: "1.2.0",
        update_available: true,
        release_url: "https://example.com/notes",
      },
    ],
  };
  updatesShouldFail = false;
  lastConfigPost = null;
  lastInstallPost = null;
  localStorage.clear();
  localStorage.setItem("homeupdater.language", "en");
});

afterEach(async () => {
  cleanup();
  vi.restoreAllMocks();
  await i18n.changeLanguage("en");
});

describe("HomeAssistantPage", () => {
  it("renders the header and connection card", async () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Home Assistant" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Connection" })).toBeInTheDocument();
    expect(screen.getByLabelText("Home Assistant URL")).toBeInTheDocument();
  });

  it("shows the not-configured badge when HA is not set up", async () => {
    renderPage();
    expect(await screen.findByText("Not configured")).toBeInTheDocument();
  });

  it("loads updates and renders an available update when connected", async () => {
    haStatus = {
      configured: true,
      enabled: true,
      connected: true,
      version: "2026.7.1",
      location_name: "Home",
      has_token: true,
    };
    renderPage();
    expect(await screen.findByText("Living Room Bulb")).toBeInTheDocument();
    expect(screen.getByText(/1\.0\.0/)).toBeInTheDocument();
    // Connected badge with version.
    expect(screen.getByText(/Connected/)).toBeInTheDocument();
  });

  it("shows the all-up-to-date empty state when there are no updates", async () => {
    haStatus = { configured: true, enabled: true, connected: true, has_token: true };
    haUpdates = { total: 2, up_to_date: 2, available: [] };
    renderPage();
    expect(await screen.findByText(/All Home Assistant devices are up to date/)).toBeInTheDocument();
  });

  it("saves the connection via POST with the entered url and token", async () => {
    renderPage();
    const urlInput = await screen.findByLabelText("Home Assistant URL");
    fireEvent.change(urlInput, { target: { value: "http://ha.local:8123" } });
    const tokenInput = screen.getByLabelText("Long-Lived Access Token");
    fireEvent.change(tokenInput, { target: { value: "secret-token" } });

    const saveBtn = screen.getByRole("button", { name: /Save & connect/ });
    expect(saveBtn).not.toBeDisabled();
    fireEvent.click(saveBtn);

    await vi.waitFor(() => {
      expect(lastConfigPost).toEqual({
        base_url: "http://ha.local:8123",
        token: "secret-token",
        enabled: true,
      });
    });
  });

  it("installs an update when the Update button is clicked", async () => {
    haStatus = { configured: true, enabled: true, connected: true, has_token: true };
    renderPage();
    await screen.findByText("Living Room Bulb");
    fireEvent.click(screen.getByRole("button", { name: /Update/ }));
    await vi.waitFor(() => {
      expect(lastInstallPost).toEqual({ entity_id: "update.living_room_bulb" });
    });
  });

  it("shows an error message when fetching updates fails", async () => {
    haStatus = { configured: true, enabled: true, connected: true, has_token: true };
    updatesShouldFail = true;
    renderPage();
    expect(await screen.findByText(/Could not fetch updates/)).toBeInTheDocument();
  });

  it("calls onBack from the dashboard button", async () => {
    const onBack = vi.fn();
    renderPage({ onBack });
    fireEvent.click(screen.getByRole("button", { name: /Dashboard/ }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
