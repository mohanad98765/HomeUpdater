import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "@/lib/language";
import i18n from "@/i18n";
import { WindowsRemotePage } from "./WindowsRemotePage";

// The remote-connection page: pick a DISCOVERED device (fills host + name), then
// connect with just username + password; host/port/TLS live under Advanced.

let apiCalls: { url: string; method: string; body: Record<string, unknown> | undefined }[];

const DEVICE = {
  id: 1,
  ip: "192.168.1.60",
  hostname: "Office-PC",
  vendor: "Dell",
  device_type: "computer",
  custom_name: "",
};

function res(status: number, body: unknown, ok = status < 400): Response {
  return { ok, status, json: async () => body } as unknown as Response;
}

function router(url: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const u = String(url);
  const m = (init?.method || "GET").toUpperCase();
  apiCalls.push({ url: u, method: m, body: init?.body ? JSON.parse(init.body as string) : undefined });
  if (u.includes("/api/winrm/hosts") && m === "POST") return Promise.resolve(res(200, { id: 1 }));
  if (u.includes("/api/winrm/hosts")) return Promise.resolve(res(200, { hosts: [], total: 0 }));
  if (u.includes("/api/devices")) return Promise.resolve(res(200, { devices: [DEVICE], total: 1 }));
  return Promise.resolve(res(404, {}));
}

function renderPage() {
  vi.stubGlobal("fetch", vi.fn(router));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <LanguageProvider>
        <WindowsRemotePage onBack={vi.fn()} />
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

const winrmPosts = () => apiCalls.filter((c) => c.url.includes("/api/winrm/hosts") && c.method === "POST");

beforeAll(async () => {
  localStorage.setItem("homeupdater.language", "en");
  await i18n.changeLanguage("en");
});

beforeEach(() => {
  apiCalls = [];
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("WindowsRemotePage device picker", () => {
  it("picking a discovered device fills the host and connects with username + password", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Add device" }));

    const picker = (await screen.findByLabelText("Pick a discovered device")) as HTMLSelectElement;
    // The discovered device is offered as an option.
    expect(screen.getByRole("option", { name: /Office-PC — 192\.168\.1\.60/ })).toBeInTheDocument();

    fireEvent.change(picker, { target: { value: "192.168.1.60" } });
    fireEvent.change(screen.getByLabelText("Username (admin)"), { target: { value: "administrator" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect & save" }));

    await waitFor(() => expect(winrmPosts()).toHaveLength(1));
    expect(winrmPosts()[0].body).toMatchObject({
      host: "192.168.1.60", // auto-filled from the picker
      username: "administrator",
      password: "secret",
      custom_name: "Office-PC", // derived from the device's name
    });
  });

  it("keeps host/port/TLS out of sight until Advanced is opened", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Add device" }));
    await screen.findByLabelText("Pick a discovered device");

    // The manual IP field is hidden by default…
    expect(screen.queryByLabelText("IP address (e.g. 192.168.1.60)")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Advanced/ }));
    // …and appears once Advanced is expanded.
    expect(screen.getByLabelText("IP address (e.g. 192.168.1.60)")).toBeInTheDocument();
  });
});
