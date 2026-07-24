import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import i18n from "@/i18n";
import { AuthGate } from "./AuthGate";

// AuthGate is the whole app's front door: it must never flash the app on a
// stale session, must gate on the real /auth/status + /auth/check answers, and
// must de-auth on the hu:unauthorized event. Backend is mocked via fetch.

const AUTH_KEY = "hu_auth_token";

// Per-test scenario knobs, reset in beforeEach.
let passwordSet = true;
let checkOk = true;
let calls: Record<string, boolean>;

beforeAll(async () => {
  try {
    localStorage.setItem("homeupdater.language", "en"); // stable assertions
  } catch {
    /* jsdom always has localStorage */
  }
  await i18n.changeLanguage("en");
});

function res(status: number, body: unknown, ok = status < 400): Response {
  return { ok, status, json: async () => body } as unknown as Response;
}

function fetchImpl(url: RequestInfo | URL): Promise<Response> {
  const u = String(url);
  if (u.includes("/api/auth/status")) return Promise.resolve(res(200, { password_set: passwordSet }));
  if (u.includes("/api/auth/check")) {
    return Promise.resolve(checkOk ? res(200, { ok: true }) : res(401, { detail: "expired" }));
  }
  if (u.includes("/api/auth/setup")) {
    calls.setup = true;
    return Promise.resolve(res(200, { token: "new-token" }));
  }
  if (u.includes("/api/auth/login")) {
    calls.login = true;
    return Promise.resolve(res(200, { token: "new-token" }));
  }
  return Promise.resolve(res(404, {}));
}

function renderGate() {
  vi.stubGlobal("fetch", vi.fn(fetchImpl));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuthGate>
        <div>APP CONTENT</div>
      </AuthGate>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  passwordSet = true;
  checkOk = true;
  calls = {};
  try {
    sessionStorage.clear();
  } catch {
    /* jsdom */
  }
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("AuthGate", () => {
  it("shows the first-run setup screen when no password is set", async () => {
    passwordSet = false; // and no stored token
    renderGate();
    expect(await screen.findByText("Create a password")).toBeInTheDocument();
    expect(screen.queryByText("APP CONTENT")).not.toBeInTheDocument();
  });

  it("shows the login screen when a password exists but no token is stored", async () => {
    passwordSet = true;
    renderGate();
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByText("APP CONTENT")).not.toBeInTheDocument();
  });

  it("renders the app once a stored token passes /auth/check", async () => {
    sessionStorage.setItem(AUTH_KEY, "good-token");
    checkOk = true;
    renderGate();
    expect(await screen.findByText("APP CONTENT")).toBeInTheDocument();
  });

  it("drops a stale token and shows login — never flashes the app", async () => {
    sessionStorage.setItem(AUTH_KEY, "stale-token");
    checkOk = false; // the gated /auth/check rejects the stale session
    renderGate();
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByText("APP CONTENT")).not.toBeInTheDocument();
    expect(sessionStorage.getItem(AUTH_KEY)).toBeNull(); // token was cleared
  });

  it("de-authenticates when a hu:unauthorized event fires", async () => {
    sessionStorage.setItem(AUTH_KEY, "good-token");
    renderGate();
    await screen.findByText("APP CONTENT"); // authed first
    fireEvent(window, new Event("hu:unauthorized"));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByText("APP CONTENT")).not.toBeInTheDocument();
  });

  it("blocks setup submit when passwords mismatch, without calling the API", async () => {
    passwordSet = false; // setup mode
    const { container } = renderGate();
    await screen.findByText("Create a password");
    fireEvent.change(container.querySelector("#auth-password")!, { target: { value: "abc123" } });
    fireEvent.change(container.querySelector("#auth-confirm")!, { target: { value: "xyz789" } });
    fireEvent.click(screen.getByRole("button")); // the only button in setup mode
    // Client-side validation must short-circuit before any /auth/setup call.
    await waitFor(() => expect(calls.setup).toBeUndefined());
  });
});
