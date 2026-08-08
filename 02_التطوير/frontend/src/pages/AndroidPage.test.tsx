import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "@/lib/language";
import { ThemeProvider } from "@/lib/theme";
import i18n from "@/i18n";
import { AndroidPage } from "./AndroidPage";

// The Android page lists paired phones from GET /api/android/devices, opens an
// "Add phone" dialog (POST /api/android/pair, /discover, /devices), and drills
// into a per-device apps view (GET /api/android/devices/:id/apps). Backend is
// fetch-mocked with the shapes from the page's interfaces.

interface AndroidDevice {
  id: number;
  host: string;
  port: number;
  serial: string;
  manufacturer: string;
  model: string;
  brand: string;
  android_version: string;
  sdk_version: string;
  security_patch: string;
  custom_name: string;
  is_online: boolean;
  display_name: string;
  first_seen: string | null;
  last_seen: string | null;
}
interface AppInfo {
  package_name: string;
  version_name: string;
  version_code: string;
  apk_path: string;
  label: string;
}

function makeDevice(over: Partial<AndroidDevice> = {}): AndroidDevice {
  return {
    id: 1,
    host: "192.168.1.42",
    port: 5555,
    serial: "R58N12ABCD",
    manufacturer: "Samsung",
    model: "SM-G991B",
    brand: "samsung",
    android_version: "13",
    sdk_version: "33",
    security_patch: "2024-05-01",
    custom_name: "",
    is_online: true,
    display_name: "Galaxy S21",
    first_seen: null,
    last_seen: null,
    ...over,
  };
}

let devices: AndroidDevice[];
let apps: AppInfo[];
let appsError: boolean;

function res(status: number, body: unknown, ok = status < 400): Response {
  return {
    ok,
    status,
    json: async () => body,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  } as unknown as Response;
}

let qrPaired = false;
const posted: { url: string; body: string }[] = [];

function router(url: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const u = String(url);
  const method = init?.method ?? "GET";
  if (method === "POST") posted.push({ url: u, body: String(init?.body ?? "") });

  // per-device apps list + open-in-store (checked first: URL contains /devices)
  if (u.includes("/apps")) {
    if (u.includes("/open")) return Promise.resolve(res(200, {}));
    if (appsError) return Promise.resolve(res(500, { detail: "adb not reachable" }));
    return Promise.resolve(res(200, { device: devices[0], apps, total: apps.length }));
  }
  if (u.includes("/api/android/pair/qr.svg")) {
    return Promise.resolve(res(200, "<svg></svg>"));
  }
  if (u.includes("/api/android/pair/qr")) {
    if (method === "DELETE") return Promise.resolve(res(200, { cancelled: true }));
    // POST starts it; GET reports it. `qrPaired` lets a test flip the session to the
    // moment the phone finished pairing.
    return Promise.resolve(
      res(
        200,
        qrPaired
          ? {
              status: "paired",
              device: { host: "192.168.3.24", port: 41234, instance: "adb-X" },
            }
          : { id: "s1", status: "waiting", seconds_left: 120, candidates: [] },
      ),
    );
  }
  if (u.includes("/api/android/pair")) {
    return Promise.resolve(res(200, { paired: true, connect_port: 41234 }));
  }
  if (u.includes("/api/android/discover")) {
    return Promise.resolve(res(200, { connect_port: 41234 }));
  }
  if (u.includes("/api/android/devices")) {
    if (u.includes("/refresh")) return Promise.resolve(res(200, devices[0]));
    if (method === "POST") return Promise.resolve(res(200, makeDevice({ id: 99 })));
    if (method === "DELETE") return Promise.resolve(res(200, { deleted: 1 }));
    if (method === "PATCH") return Promise.resolve(res(200, devices[0]));
    return Promise.resolve(res(200, { devices, total: devices.length }));
  }
  return Promise.resolve(res(200, {}));
}

function renderPage(props: Partial<Parameters<typeof AndroidPage>[0]> = {}) {
  vi.stubGlobal("fetch", vi.fn(router));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <LanguageProvider>
          <AndroidPage onBack={() => {}} {...props} />
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
  devices = [];
  apps = [];
  appsError = false;
  localStorage.clear();
  localStorage.setItem("homeupdater.language", "en");
});

afterEach(async () => {
  cleanup();
  vi.restoreAllMocks();
  await i18n.changeLanguage("en");
});

describe("AndroidPage", () => {
  it("renders the title and add-phone action", async () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Android phones" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Add phone/ })).toBeInTheDocument();
  });

  it("shows the empty state when there are no devices", async () => {
    renderPage();
    expect(await screen.findByText("No phones added yet")).toBeInTheDocument();
    expect(screen.getByText("Click Add phone to start managing your devices")).toBeInTheDocument();
  });

  it("loads devices and renders a device card", async () => {
    devices = [makeDevice({ display_name: "Galaxy S21", is_online: true })];
    renderPage();
    expect(await screen.findByRole("heading", { name: "Galaxy S21" })).toBeInTheDocument();
    expect(screen.getByText("Online")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /View apps/ })).toBeInTheDocument();
  });

  it("opens the add-phone dialog", async () => {
    renderPage();
    await screen.findByText("No phones added yet");
    fireEvent.click(screen.getAllByRole("button", { name: /Add phone/ })[0]);
    expect(await screen.findByText("Add an Android phone")).toBeInTheDocument();
    expect(screen.getByText("How do I connect my phone?")).toBeInTheDocument();
  });

  it("drills into a device's apps and lists a package", async () => {
    devices = [makeDevice({ id: 7, display_name: "Galaxy S21" })];
    apps = [
      {
        package_name: "com.example.messenger",
        version_name: "2.4.1",
        version_code: "241",
        apk_path: "/data/app/com.example.messenger.apk",
        label: "Messenger",
      },
    ];
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /View apps/ }));
    expect(await screen.findByText("com.example.messenger")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Galaxy S21 apps" })).toBeInTheDocument();
  });

  it("shows an error when the apps list fails to load", async () => {
    devices = [makeDevice({ id: 7, display_name: "Galaxy S21" })];
    appsError = true;
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /View apps/ }));
    expect(await screen.findByText("adb not reachable")).toBeInTheDocument();
  });

  it("calls onBack from the header dashboard button", async () => {
    const onBack = vi.fn();
    renderPage({ onBack });
    fireEvent.click(screen.getByRole("button", { name: /Dashboard/ }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});

describe("pairing by QR ends with the phone in the list", () => {
  it("registers the phone itself, with no second click", async () => {
    // What the operator asked for after using it: "when I scan the code, the device
    // should be added". The first version only filled the form and waited for a click
    // on Add phone, which reads as "it did not work".
    qrPaired = false;
    posted.length = 0;
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /إضافة هاتف|add phone/i }));
    fireEvent.click(await screen.findByRole("button", { name: /show the pairing code/i }));
    await screen.findByRole("img", { name: /pairing code/i });

    qrPaired = true;  // the phone finished pairing
    await waitFor(
      () => expect(posted.some((p) => p.url.endsWith("/api/android/devices"))).toBe(true),
      { timeout: 5000 },
    );
    const add = posted.find((p) => p.url.endsWith("/api/android/devices"))!;
    expect(JSON.parse(add.body)).toEqual({ host: "192.168.3.24", port: 41234 });
  });
});
