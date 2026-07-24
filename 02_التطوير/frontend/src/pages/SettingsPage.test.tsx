import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "@/lib/language";
import { ThemeProvider } from "@/lib/theme";
import i18n from "@/i18n";
import { SettingsPage } from "./SettingsPage";

// The in-app Settings page: theme + language apply instantly (localStorage);
// scan settings load from GET /api/system/settings and save via POST. Backend
// is fetch-mocked; the POST echoes the applied values back.

interface ScanSettings {
  scan_method: "auto" | "python" | "nmap";
  scan_scheduler_enabled: boolean;
  scan_interval_minutes: number;
}

let scanSettings: ScanSettings;
let lastPost: Record<string, unknown> | null;

function res(status: number, body: unknown, ok = status < 400): Response {
  return { ok, status, json: async () => body } as unknown as Response;
}

function router(url: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const u = String(url);
  const method = init?.method ?? "GET";
  if (u.includes("/api/system/settings")) {
    if (method === "POST") {
      lastPost = JSON.parse(String(init!.body));
      scanSettings = { ...scanSettings, ...(lastPost as Partial<ScanSettings>) };
      return Promise.resolve(res(200, { ...scanSettings, applied: Object.keys(lastPost!) }));
    }
    return Promise.resolve(res(200, scanSettings));
  }
  return Promise.resolve(res(200, {}));
}

function renderPage(props: Partial<Parameters<typeof SettingsPage>[0]> = {}) {
  vi.stubGlobal("fetch", vi.fn(router));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <LanguageProvider>
          <SettingsPage onBack={() => {}} onOpenAdvisor={() => {}} {...props} />
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
  scanSettings = { scan_method: "auto", scan_scheduler_enabled: false, scan_interval_minutes: 30 };
  lastPost = null;
  localStorage.clear();
  localStorage.setItem("homeupdater.language", "en");
});

afterEach(async () => {
  cleanup();
  vi.restoreAllMocks();
  await i18n.changeLanguage("en");
});

describe("SettingsPage", () => {
  it("renders the theme and language pickers", async () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Appearance" })).toBeInTheDocument();
    expect(screen.getByText("Ocean")).toBeInTheDocument(); // a theme option
    expect(screen.getByText("Français")).toBeInTheDocument(); // a language option (native name)
  });

  it("loads scan settings and shows the current method", async () => {
    scanSettings.scan_method = "python";
    renderPage();
    const select = (await screen.findByLabelText("Scan method")) as HTMLSelectElement;
    expect(select.value).toBe("python");
  });

  it("saves changed scan settings via POST and confirms", async () => {
    renderPage();
    const select = (await screen.findByLabelText("Scan method")) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "nmap" } });

    const saveBtn = screen.getByRole("button", { name: /Save scan settings/ });
    expect(saveBtn).not.toBeDisabled();
    fireEvent.click(saveBtn);

    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(lastPost).toEqual({
      scan_method: "nmap",
      scan_scheduler_enabled: false,
      scan_interval_minutes: 30,
    });
  });

  it("keeps Save disabled until something changes", async () => {
    renderPage();
    await screen.findByLabelText("Scan method");
    expect(screen.getByRole("button", { name: /Save scan settings/ })).toBeDisabled();
  });

  it("applies a theme choice instantly to localStorage", async () => {
    renderPage();
    fireEvent.click(screen.getByText("Ocean"));
    expect(localStorage.getItem("homeupdater.theme")).toBe("ocean");
  });

  it("switches language on click", async () => {
    renderPage();
    fireEvent.click(screen.getByText("Français"));
    expect(localStorage.getItem("homeupdater.language")).toBe("fr");
  });

  it("toggles the scheduler switch", async () => {
    renderPage();
    const sw = await screen.findByRole("switch", { name: "Scheduled automatic scan" });
    expect(sw).toHaveAttribute("aria-checked", "false");
    fireEvent.click(sw);
    expect(sw).toHaveAttribute("aria-checked", "true");
  });

  it("opens advisor settings via the callback", async () => {
    const onOpenAdvisor = vi.fn();
    renderPage({ onOpenAdvisor });
    fireEvent.click(screen.getByRole("button", { name: /Open advisor settings/ }));
    expect(onOpenAdvisor).toHaveBeenCalledTimes(1);
  });

  it("calls onBack from the header button", async () => {
    const onBack = vi.fn();
    renderPage({ onBack });
    fireEvent.click(screen.getByRole("button", { name: /Dashboard/ }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
