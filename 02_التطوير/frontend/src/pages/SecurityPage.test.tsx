import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "@/lib/language";
import { ThemeProvider } from "@/lib/theme";
import i18n from "@/i18n";
import { SecurityPage } from "./SecurityPage";

// The Security page loads GET /api/security/overview (per-device known CVEs by
// vendor), lets you re-scan via POST /api/security/refresh, and run a manual
// keyword check via GET /api/security/cves?keyword=... . Backend is fetch-mocked.

interface DeviceCVE {
  device_id: number;
  display_name: string;
  ip: string;
  vendor: string;
  cve_total: number | null;
  top_severity: string | null;
  top_cve: string | null;
  top_cve_url: string | null;
  checked: boolean;
}
interface Overview {
  devices: DeviceCVE[];
  vendors_total: number;
  vendors_checked: number;
}

let overview: Overview;
let cvesFail: boolean;
let refreshCalled: boolean;

function res(status: number, body: unknown, ok = status < 400): Response {
  return { ok, status, json: async () => body } as unknown as Response;
}

function router(url: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const u = String(url);
  const method = init?.method ?? "GET";
  if (u.includes("/api/security/overview")) {
    return Promise.resolve(res(200, overview));
  }
  if (u.includes("/api/security/refresh") && method === "POST") {
    refreshCalled = true;
    return Promise.resolve(res(200, {}));
  }
  if (u.includes("/api/security/cves")) {
    if (cvesFail) return Promise.resolve(res(500, { detail: "boom" }));
    return Promise.resolve(
      res(200, {
        keyword: "cisco",
        total_results: 42,
        cves: [
          {
            id: "CVE-2021-1234",
            score: 9.8,
            severity: "CRITICAL",
            published: "2021-01-01",
            description: "A serious flaw.",
            url: "https://nvd.nist.gov/vuln/detail/CVE-2021-1234",
          },
        ],
        fetched_at: null,
        cached: false,
      }),
    );
  }
  return Promise.resolve(res(200, {}));
}

function device(over: Partial<DeviceCVE> = {}): DeviceCVE {
  return {
    device_id: 1,
    display_name: "Living Room Router",
    ip: "192.168.1.1",
    vendor: "Cisco",
    cve_total: 3,
    top_severity: "HIGH",
    top_cve: "CVE-2020-0001",
    top_cve_url: "https://nvd.nist.gov/vuln/detail/CVE-2020-0001",
    checked: true,
    ...over,
  };
}

function renderPage(props: Partial<Parameters<typeof SecurityPage>[0]> = {}) {
  vi.stubGlobal("fetch", vi.fn(router));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <LanguageProvider>
          <SecurityPage onBack={() => {}} {...props} />
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
  overview = { devices: [], vendors_total: 0, vendors_checked: 0 };
  cvesFail = false;
  refreshCalled = false;
  localStorage.clear();
  localStorage.setItem("homeupdater.language", "en");
});

afterEach(async () => {
  cleanup();
  vi.restoreAllMocks();
  await i18n.changeLanguage("en");
});

describe("SecurityPage", () => {
  it("renders the title and subtitle", async () => {
    renderPage();
    expect(
      screen.getByRole("heading", { name: "Security — known vulnerabilities" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Security · known vulnerabilities (NVD)")).toBeInTheDocument();
  });

  it("shows the empty state when no device has a known vendor", async () => {
    renderPage();
    expect(await screen.findByText(/No devices with a known vendor yet/)).toBeInTheDocument();
  });

  it("loads the overview and renders a device row", async () => {
    overview = { devices: [device()], vendors_total: 1, vendors_checked: 1 };
    renderPage();
    expect(await screen.findByText("Living Room Router")).toBeInTheDocument();
    expect(screen.getByText("192.168.1.1")).toBeInTheDocument();
    // Vendor appears in the table; there are two "Cisco"-ish cells but vendor is exact.
    expect(screen.getByRole("cell", { name: "Cisco" })).toBeInTheDocument();
  });

  it("runs a manual vendor check and renders CVE results", async () => {
    renderPage();
    const input = screen.getByLabelText("Manual check for any vendor");
    fireEvent.change(input, { target: { value: "cisco" } });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));

    expect(await screen.findByText("CVE-2021-1234")).toBeInTheDocument();
    expect(screen.getByText(/known vulnerabilities total/)).toBeInTheDocument();
  });

  it("shows an error when the manual check fails", async () => {
    cvesFail = true;
    renderPage();
    const input = screen.getByLabelText("Manual check for any vendor");
    fireEvent.change(input, { target: { value: "cisco" } });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));

    expect(await screen.findByText(/Check failed/)).toBeInTheDocument();
    expect(screen.getByText(/boom/)).toBeInTheDocument();
  });

  it("triggers a re-scan via the Check vulnerabilities button", async () => {
    overview = { devices: [device()], vendors_total: 1, vendors_checked: 1 };
    renderPage();
    // Wait for the overview so the scan button becomes enabled.
    await screen.findByText("Living Room Router");
    const scanBtn = screen.getByRole("button", { name: /Check vulnerabilities/ });
    expect(scanBtn).not.toBeDisabled();
    fireEvent.click(scanBtn);
    await vi.waitFor(() => expect(refreshCalled).toBe(true));
  });

  it("disables the scan button when no vendor is known", async () => {
    renderPage();
    await screen.findByText(/No devices with a known vendor yet/);
    expect(screen.getByRole("button", { name: /Check vulnerabilities/ })).toBeDisabled();
  });

  it("calls onBack from the dashboard button", async () => {
    const onBack = vi.fn();
    renderPage({ onBack });
    fireEvent.click(screen.getByRole("button", { name: /Dashboard/ }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
