import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "@/lib/language";
import { ThemeProvider } from "@/lib/theme";
import i18n from "@/i18n";
import { EvidencePage } from "./EvidencePage";

// This page sells something, so the tests police the promises: the stamp must never
// read as a signature, the free preview must expose the coverage gap before payment,
// export must stay locked without a license, and a rejected pack must be visible.

interface Lic {
  tier: string;
  licensee: string;
  devices_max: number;
  expires: string;
  issued_at: string;
  key_id: string;
  valid: boolean;
  expired: boolean;
  reason: string;
  can_export_evidence: boolean;
}

let license: Lic;
let preview: Record<string, unknown>;
let rollup: Record<string, unknown> | null;
let activateStatus: number;
let calls: string[];

const UNLICENSED: Lic = {
  tier: "free",
  licensee: "",
  devices_max: 0,
  expires: "",
  issued_at: "",
  key_id: "",
  valid: false,
  expired: false,
  reason: "none",
  can_export_evidence: false,
};

function res(status: number, body: unknown, ok = status < 400): Response {
  return {
    ok,
    status,
    json: async () => body,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  } as unknown as Response;
}

function router(url: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const u = String(url);
  calls.push(`${init?.method ?? "GET"} ${u}`);
  if (u.includes("/license/activate")) {
    return Promise.resolve(
      activateStatus === 200
        ? res(200, { ...license, tier: "evidence25", can_export_evidence: true, valid: true })
        : res(400, { detail: "bad_signature" }),
    );
  }
  if (u.includes("/license/clear")) return Promise.resolve(res(200, { ok: true }));
  if (u.includes("/api/evidence/license")) return Promise.resolve(res(200, license));
  if (u.includes("/api/evidence/preview")) return Promise.resolve(res(200, preview));
  if (u.includes("/api/evidence/rollup")) {
    return rollup
      ? Promise.resolve(res(200, rollup))
      : Promise.resolve(res(402, { detail: "partner_tier_required" }));
  }
  if (u.includes("/api/evidence/pack")) {
    return license.can_export_evidence
      ? Promise.resolve(res(200, { pack: {}, content_sha256: "f".repeat(64) }))
      : Promise.resolve(res(402, { detail: "not_licensed" }));
  }
  return Promise.resolve(res(200, {}));
}

function renderPage() {
  vi.stubGlobal("fetch", vi.fn(router));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <LanguageProvider>
          <EvidencePage onBack={() => {}} />
        </LanguageProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

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
  // jsdom has no Blob URL plumbing; the download helper only needs it not to throw.
  URL.createObjectURL = URL.createObjectURL || (() => "blob:mock");
  URL.revokeObjectURL = URL.revokeObjectURL || (() => {});
  localStorage.setItem("homeupdater.language", "en");
  await i18n.changeLanguage("en");
});

beforeEach(() => {
  calls = [];
  activateStatus = 200;
  rollup = null;
  license = { ...UNLICENSED };
  preview = {
    inventory_total: 40,
    coverage: { total: 40, mapped: 21, unmapped: 19, percent: 52.5 },
    findings_total: 3,
    broad_matches_total: 4,
    unmatched_total: 19,
    audit: { chain_ok: true, entries: 12, broken_at: null, head_hash: "a".repeat(64) },
    licensed: false,
  };
  localStorage.clear();
  localStorage.setItem("homeupdater.language", "en");
});

afterEach(async () => {
  cleanup();
  vi.restoreAllMocks();
  await i18n.changeLanguage("en");
});

describe("EvidencePage", () => {
  it("shows the free preview with the coverage gap before any payment", async () => {
    renderPage();
    expect(await screen.findByText("52.5%")).toBeInTheDocument();
    expect(screen.getByText(/21 of 40 can be matched precisely/)).toBeInTheDocument();
    expect(screen.getByText("no license")).toBeInTheDocument();
  });

  it("never calls the stamp a signature", async () => {
    renderPage();
    expect(await screen.findByText(/NOT a digital signature/)).toBeInTheDocument();
    expect(screen.getByText(/does not attest to the issuer/)).toBeInTheDocument();
  });

  it("states that no findings is not proof of clean", async () => {
    renderPage();
    expect(
      await screen.findByText(/not that a product is free of flaws/),
    ).toBeInTheDocument();
    expect(screen.getByText(/not a certification/)).toBeInTheDocument();
  });

  it("keeps export disabled until licensed", async () => {
    renderPage();
    const csv = await screen.findByRole("button", { name: /^CSV$/ });
    expect(csv).toBeDisabled();
    expect(screen.getByRole("button", { name: /^JSON$/ })).toBeDisabled();
  });

  it("enables export after a successful activation", async () => {
    renderPage();
    fireEvent.change(await screen.findByLabelText("License key"), {
      target: { value: "HU1.aaaa.bbbb" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Activate/ }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^CSV$/ })).not.toBeDisabled(),
    );
    expect(screen.getByText(/Active — evidence25 tier/)).toBeInTheDocument();
  });

  it("surfaces an activation failure", async () => {
    activateStatus = 400;
    renderPage();
    fireEvent.change(await screen.findByLabelText("License key"), {
      target: { value: "HU1.forged.key" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Activate/ }));
    expect(await screen.findByText(/bad_signature/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^CSV$/ })).toBeDisabled();
  });

  it("warns loudly when the audit chain is broken", async () => {
    preview = {
      ...preview,
      audit: { chain_ok: false, entries: 12, broken_at: 7, head_hash: "b".repeat(64) },
    };
    renderPage();
    expect(await screen.findByText(/broken at entry 7/)).toBeInTheDocument();
  });

  it("hides the roll-up behind the partner tier", async () => {
    license = { ...license, tier: "evidence25", valid: true, can_export_evidence: true };
    renderPage();
    expect(await screen.findByText(/partner tier only/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Roll up/ })).not.toBeInTheDocument();
  });

  it("shows the roll-up table and the rejected packs for a partner", async () => {
    license = { ...license, tier: "partner", valid: true, can_export_evidence: true };
    rollup = {
      sites: [
        {
          site: "Clinic A",
          generated_at: "2026-07-25T10:00:00Z",
          inventory_total: 12,
          coverage_percent: 50,
          findings_total: 2,
          unmatched_total: 6,
          chain_ok: true,
          stamp: "s1",
        },
        {
          site: "Broken Site",
          generated_at: "2026-07-25T10:00:00Z",
          inventory_total: 8,
          coverage_percent: 40,
          findings_total: 0,
          unmatched_total: 4,
          chain_ok: false,
          stamp: "s2",
        },
      ],
      rejected: [{ index: 0, reason: "stamp_mismatch" }],
      totals: {
        sites_verified: 2,
        sites_rejected: 1,
        devices: 20,
        findings: 2,
        sites_with_findings: 1,
        sites_with_broken_chain: 1,
        avg_coverage_percent: 45,
      },
    };
    renderPage();

    const picker = await screen.findByLabelText("Choose pack files");
    const file = new File([JSON.stringify({ pack: {}, content_sha256: "x" })], "a.json", {
      type: "application/json",
    });
    // jsdom does not implement Blob.text(); Chromium (WebView2) does, so this is a
    // test-environment shim rather than a gap in the page.
    Object.defineProperty(file, "text", {
      value: async () => JSON.stringify({ pack: {}, content_sha256: "x" }),
    });
    fireEvent.change(picker, { target: { files: [file] } });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Roll up 1 pack/ })).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: /Roll up 1 pack/ }));

    expect(await screen.findByText("Clinic A")).toBeInTheDocument();
    expect(screen.getByText("Broken Site")).toBeInTheDocument();
    expect(screen.getByText("BROKEN")).toBeInTheDocument();
    // A rejected pack must be shown, with its reason — hiding it would launder it.
    expect(screen.getByText(/1 pack\(s\) rejected/)).toBeInTheDocument();
    expect(screen.getByText(/stamp does not match the content/)).toBeInTheDocument();
    expect(screen.getByText(/Excluded from every number/)).toBeInTheDocument();
  });

  it("does not fetch the pack on load — export is explicit", async () => {
    renderPage();
    await screen.findByText("52.5%");
    expect(calls.some((c) => c.includes("/api/evidence/pack"))).toBe(false);
  });
});
