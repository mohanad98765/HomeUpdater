import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "@/lib/language";
import { ThemeProvider } from "@/lib/theme";
import i18n from "@/i18n";
import { PreciseFindings } from "./PreciseFindings";

// The precise view's whole job is to be honest about what it can and cannot prove.
// These tests pin the three ways that could silently break: an unbounded NVD match
// presented as confirmed, an unmatched product hidden instead of explained, and a
// coverage figure that isn't shown at all.

interface Precise {
  match_mode: string;
  matched: unknown[];
  unmatched: unknown[];
  coverage: { total: number; mapped: number; unmapped: number; percent: number };
}

let precise: Precise;
let refreshCalls: string[];

function res(status: number, body: unknown, ok = status < 400): Response {
  return { ok, status, json: async () => body } as unknown as Response;
}

function router(url: RequestInfo | URL, _init?: RequestInit): Promise<Response> {
  const u = String(url);
  if (u.includes("/api/updates/inventory/refresh")) {
    refreshCalls.push("inventory");
    return Promise.resolve(res(200, { total: 1, new: 1, removed: 0, degraded: false }));
  }
  if (u.includes("/api/security/precise")) {
    if (u.includes("refresh_nvd=true")) refreshCalls.push("nvd");
    return Promise.resolve(res(200, precise));
  }
  return Promise.resolve(res(200, {}));
}

function renderIt() {
  vi.stubGlobal("fetch", vi.fn(router));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <LanguageProvider>
          <PreciseFindings />
        </LanguageProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const bounded = {
  id: "CVE-2026-58052",
  score: 3.3,
  severity: "LOW",
  published: "2026-07-01",
  description: "A flaw in the archive parser.",
  url: "https://nvd.nist.gov/vuln/detail/CVE-2026-58052",
  applies_because: { precision: "bounded", end_including: "26.02" },
};
const broad = {
  id: "CVE-2009-2940",
  score: 5.0,
  severity: "MEDIUM",
  published: "2009-08-01",
  description: "Ancient record with no version bounds.",
  url: "https://nvd.nist.gov/vuln/detail/CVE-2009-2940",
  applies_because: { precision: "unbounded" },
};

beforeAll(async () => {
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
  refreshCalls = [];
  precise = {
    match_mode: "cpe",
    matched: [],
    unmatched: [],
    coverage: { total: 0, mapped: 0, unmapped: 0, percent: 0 },
  };
  localStorage.clear();
  localStorage.setItem("homeupdater.language", "en");
});

afterEach(async () => {
  cleanup();
  vi.restoreAllMocks();
  await i18n.changeLanguage("en");
});

describe("PreciseFindings", () => {
  it("prompts for an inventory when there is none", async () => {
    renderIt();
    expect(await screen.findByText(/No inventory yet/)).toBeInTheDocument();
  });

  it("always shows the coverage figure so the gap is visible", async () => {
    precise.coverage = { total: 40, mapped: 21, unmapped: 19, percent: 52.5 };
    renderIt();
    expect(await screen.findByText(/21 of 40 products can be matched precisely/)).toBeInTheDocument();
  });

  it("renders a bounded finding with the CPE and the reason it applies", async () => {
    precise.coverage = { total: 1, mapped: 1, unmapped: 0, percent: 100 };
    precise.matched = [
      {
        product_id: "7zip.7zip",
        name: "7-Zip",
        version: "26.02",
        reported_version: "26.02",
        cpe_name: "cpe:2.3:a:7-zip:7-zip:26.02:*:*:*:*:*:*:*",
        confidence: "high",
        caveat: "",
        total_results: 1,
        cves: [bounded],
        broad_matches: [],
        fetched_at: "2026-07-25T10:00:00Z",
      },
    ];
    renderIt();
    expect(await screen.findByText("CVE-2026-58052")).toBeInTheDocument();
    // the CPE actually queried is shown, so the claim can be reproduced
    expect(screen.getByText("cpe:2.3:a:7-zip:7-zip:26.02:*:*:*:*:*:*:*")).toBeInTheDocument();
    expect(screen.getByText(/up to 26.02/)).toBeInTheDocument();
  });

  it("separates unbounded NVD records instead of showing them as confirmed", async () => {
    precise.coverage = { total: 1, mapped: 1, unmapped: 0, percent: 100 };
    precise.matched = [
      {
        product_id: "Google.Chrome",
        name: "Google Chrome",
        version: "150.0.7871.187",
        reported_version: "150.0.7871.187",
        cpe_name: "cpe:2.3:a:google:chrome:150.0.7871.187:*:*:*:*:*:*:*",
        confidence: "high",
        caveat: "",
        total_results: 2,
        cves: [bounded],
        broad_matches: [broad],
        fetched_at: null,
      },
    ];
    renderIt();
    expect(await screen.findByText(/broad match/)).toBeInTheDocument();
    expect(screen.getByText(/no version bounds/)).toBeInTheDocument();
    expect(screen.getByText("CVE-2009-2940")).toBeInTheDocument();
  });

  it("shows that a version was trimmed to match NVD numbering", async () => {
    precise.coverage = { total: 1, mapped: 1, unmapped: 0, percent: 100 };
    precise.matched = [
      {
        product_id: "Git.Git",
        name: "Git",
        version: "2.55.0",
        reported_version: "2.55.0.3",
        cpe_name: "cpe:2.3:a:git:git:2.55.0:*:*:*:*:*:*:*",
        confidence: "medium",
        caveat: "Git-for-Windows revision suffix trimmed.",
        total_results: 1,
        cves: [bounded],
        broad_matches: [],
        fetched_at: null,
      },
    ];
    renderIt();
    expect(await screen.findByText(/2.55.0.3 → queried as 2.55.0/)).toBeInTheDocument();
    expect(screen.getByText("medium confidence")).toBeInTheDocument();
    expect(screen.getByText(/revision suffix trimmed/)).toBeInTheDocument();
  });

  it("explains every unmatched product instead of hiding it", async () => {
    precise.coverage = { total: 2, mapped: 0, unmapped: 2, percent: 0 };
    precise.unmatched = [
      {
        product_id: "Microsoft.Teams",
        name: "Teams",
        version: "26183.1903",
        reason: "no_cpe_mapping",
        detail: "Installed build vs NVD 1.6.x — no comparable scheme.",
      },
      { product_id: "Python.Launcher", name: "Python Launcher", version: "> 3.13.5", reason: "version_not_comparable" },
    ];
    renderIt();
    const toggle = await screen.findByRole("button", { name: /2 product\(s\) with no precise match/ });
    fireEvent.click(toggle);
    expect(screen.getByText("Microsoft.Teams")).toBeInTheDocument();
    expect(screen.getByText("no verified CPE")).toBeInTheDocument();
    expect(screen.getByText("version not comparable")).toBeInTheDocument();
    expect(screen.getByText(/no comparable scheme/)).toBeInTheDocument();
  });

  it("says 'no data' rather than 'clean' for products with no findings", async () => {
    precise.coverage = { total: 1, mapped: 1, unmapped: 0, percent: 100 };
    precise.matched = [
      {
        product_id: "GlavSoft.TightVNC",
        name: "TightVNC",
        version: "2.8.88",
        reported_version: "2.8.88.0",
        cpe_name: "cpe:2.3:a:tightvnc:tightvnc:2.8.88:*:*:*:*:*:*:*",
        confidence: "medium",
        caveat: "",
        total_results: 0,
        cves: [],
        broad_matches: [],
        fetched_at: null,
      },
    ];
    renderIt();
    expect(await screen.findByText(/1 product\(s\) checked with no CVE/)).toBeInTheDocument();
    expect(screen.getByText(/does not prove it is clean/)).toBeInTheDocument();
  });

  it("refreshes the inventory and only queries NVD when asked", async () => {
    precise.coverage = { total: 1, mapped: 1, unmapped: 0, percent: 100 };
    renderIt();
    // The initial load must not hit NVD.
    expect(refreshCalls).not.toContain("nvd");

    fireEvent.click(await screen.findByRole("button", { name: /Refresh software inventory/ }));
    await waitFor(() => expect(refreshCalls).toContain("inventory"));
    fireEvent.click(screen.getByRole("button", { name: /Check precise vulnerabilities/ }));
    await waitFor(() => expect(refreshCalls).toContain("nvd"));
  });

  it("disables the NVD check while nothing is mappable", async () => {
    renderIt();
    const btn = await screen.findByRole("button", { name: /Check precise vulnerabilities/ });
    expect(btn).toBeDisabled();
  });
});
