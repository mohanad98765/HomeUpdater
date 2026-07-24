import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "@/lib/language";
import { ThemeProvider } from "@/lib/theme";
import i18n from "@/i18n";
import { DevicesPage } from "./DevicesPage";

// The Devices page loads network info, the device list, and stats from the
// backend (all fetch-mocked here). The "Scan network now" button fires a
// background scan (POST /api/devices/scan) and then polls /scan/status.

interface Device {
  id: number;
  ip: string;
  mac: string;
  hostname: string;
  vendor: string;
  device_type: string;
  status: "online" | "offline";
  custom_name: string;
  notes: string;
  display_name: string;
  first_seen: string | null;
  last_seen: string | null;
  manageable?: boolean;
}

let networkInfo: unknown;
let deviceList: { devices: Device[]; total: number; subnet: string };
let deviceStats: unknown;
let progressState: unknown;
let lastScanBody: Record<string, unknown> | null;

function sampleDevice(over: Partial<Device> = {}): Device {
  return {
    id: 1,
    ip: "192.168.1.42",
    mac: "AA:BB:CC:DD:EE:FF",
    hostname: "living-room-pc",
    vendor: "Dell Inc.",
    device_type: "computer",
    status: "online",
    custom_name: "",
    notes: "",
    display_name: "living-room-pc",
    first_seen: null,
    last_seen: null,
    manageable: true,
    ...over,
  };
}

function res(status: number, body: unknown, ok = status < 400): Response {
  return { ok, status, json: async () => body } as unknown as Response;
}

function router(url: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const u = String(url);
  const method = init?.method ?? "GET";
  if (u.includes("/api/devices/scan/status")) {
    return Promise.resolve(res(200, progressState));
  }
  if (u.includes("/api/devices/scan")) {
    if (method === "POST") {
      lastScanBody = JSON.parse(String(init!.body));
      return Promise.resolve(res(200, { started: true, subnet: "192.168.1.0/24" }));
    }
    return Promise.resolve(res(200, {}));
  }
  if (u.includes("/api/devices/stats")) {
    return Promise.resolve(res(200, deviceStats));
  }
  if (u.includes("/api/devices/info")) {
    return Promise.resolve(res(200, networkInfo));
  }
  if (u.includes("/api/devices")) {
    return Promise.resolve(res(200, deviceList));
  }
  return Promise.resolve(res(200, {}));
}

function renderPage(props: Partial<Parameters<typeof DevicesPage>[0]> = {}) {
  vi.stubGlobal("fetch", vi.fn(router));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <LanguageProvider>
          <DevicesPage onBack={() => {}} {...props} />
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
  networkInfo = {
    local_ip: "192.168.1.10",
    netmask: "255.255.255.0",
    raw_subnet: "192.168.1.0/24",
    suggested_subnet: "192.168.1.0/24",
    gateway_ip: "192.168.1.1",
    interface_name: "Ethernet",
    interfaces: [],
    stored_devices: 0,
  };
  deviceList = { devices: [], total: 0, subnet: "192.168.1.0/24" };
  deviceStats = { total: 0, online: 0, offline: 0, by_type: {} };
  progressState = {
    is_running: true,
    phase: "scanning",
    subnet: "192.168.1.0/24",
    devices_count: 0,
    elapsed_seconds: 1.5,
    last_message: "scanning…",
    error: null,
    log: [],
  };
  lastScanBody = null;
  localStorage.clear();
  localStorage.setItem("homeupdater.language", "en");
});

afterEach(async () => {
  cleanup();
  vi.restoreAllMocks();
  await i18n.changeLanguage("en");
});

describe("DevicesPage", () => {
  it("renders the page title and the scan button", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Network devices" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Scan network now/ })).toBeInTheDocument();
  });

  it("shows the empty state when no devices are found", async () => {
    renderPage();
    expect(await screen.findByText("No devices discovered yet")).toBeInTheDocument();
    expect(screen.getByText(/Click .* to search your home network/)).toBeInTheDocument();
  });

  it("loads and renders a discovered device row", async () => {
    deviceList = {
      devices: [sampleDevice()],
      total: 1,
      subnet: "192.168.1.0/24",
    };
    renderPage();
    expect(await screen.findByText("living-room-pc")).toBeInTheDocument();
    expect(screen.getByText("192.168.1.42")).toBeInTheDocument();
    expect(screen.getByText("Dell Inc.")).toBeInTheDocument();
  });

  it("renders the network info card with the local IP and gateway", async () => {
    renderPage();
    expect(await screen.findByText("192.168.1.10")).toBeInTheDocument(); // local IP
    expect(screen.getByRole("heading", { name: "Network info" })).toBeInTheDocument();
    expect(screen.getByText("192.168.1.1")).toBeInTheDocument(); // gateway
  });

  it("starts a background scan via POST when the scan button is clicked", async () => {
    renderPage();
    // The scan button is disabled until network info supplies a subnet.
    const scanBtn = screen.getByRole("button", { name: /Scan network now/ });
    await waitFor(() => expect(scanBtn).not.toBeDisabled());

    fireEvent.click(scanBtn);

    await waitFor(() => expect(lastScanBody).toEqual({ subnet: "192.168.1.0/24" }));
    // After a successful POST the UI switches into the scanning state.
    expect((await screen.findAllByText("Scanning network…")).length).toBeGreaterThan(0);
  });

  it("renders the stats cards", async () => {
    deviceStats = { total: 5, online: 3, offline: 2, by_type: { router: 1, phone: 2 } };
    renderPage();
    expect(await screen.findByText("Total devices")).toBeInTheDocument();
    expect(screen.getByText("Online now")).toBeInTheDocument();
    expect(screen.getByText("Routers")).toBeInTheDocument();
  });

  it("calls onBack from the dashboard button", () => {
    const onBack = vi.fn();
    renderPage({ onBack });
    fireEvent.click(screen.getByRole("button", { name: /Dashboard/ }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
