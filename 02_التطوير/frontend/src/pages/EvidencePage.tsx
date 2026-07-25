import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  ArrowRight,
  FileCheck2,
  KeyRound,
  Loader2,
  Download,
  ShieldCheck,
  ShieldX,
  Users,
  Upload,
  AlertTriangle,
  Info,
} from "lucide-react";
import { apiFetch, apiFetchText, cn, downloadText, type ApiError } from "@/lib/utils";
import { useLanguage } from "@/lib/language";

// ================================================================
// حزمة الدليل + الترخيص.
// المبدأ الحاكم في العرض: لا وعد بما لا نملكه.
//   • البصمة تُسمّى «بصمة هاش» ويُقال صريحًا إنها ليست توقيعًا رقميًّا.
//   • المعاينة مجانيّة وتُظهر التغطية الناقصة قبل الدفع.
//   • الحزم المرفوضة في التجميع تُعرَض، ولا تُطوى في المجموع.
// ================================================================

interface LicenseInfo {
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
interface Preview {
  inventory_total: number;
  coverage: { total: number; mapped: number; unmapped: number; percent: number };
  findings_total: number;
  broad_matches_total: number;
  unmatched_total: number;
  audit: { chain_ok: boolean; entries: number; broken_at: number | null; head_hash: string };
  licensed: boolean;
}
interface RollupSite {
  site: string;
  generated_at: string;
  inventory_total: number;
  coverage_percent: number;
  findings_total: number;
  unmatched_total: number;
  chain_ok: boolean;
  stamp: string;
}
interface Rollup {
  sites: RollupSite[];
  rejected: { index: number; reason: string }[];
  totals: {
    sites_verified: number;
    sites_rejected: number;
    products: number;
    findings: number;
    sites_with_findings: number;
    sites_with_broken_chain: number;
    avg_coverage_percent: number;
  };
}

export function EvidencePage({ onBack }: { onBack: () => void }) {
  const { t } = useTranslation();
  const { dir } = useLanguage();
  const qc = useQueryClient();
  const BackIcon = dir === "rtl" ? ArrowRight : ArrowLeft;

  const [keyText, setKeyText] = useState("");
  const [rollup, setRollup] = useState<Rollup | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const license = useQuery<LicenseInfo>({
    queryKey: ["license"],
    queryFn: () => apiFetch<LicenseInfo>("/api/evidence/license"),
  });
  const preview = useQuery<Preview>({
    queryKey: ["evidence-preview"],
    queryFn: () => apiFetch<Preview>("/api/evidence/preview"),
  });

  const activate = useMutation<LicenseInfo, Error, string>({
    mutationFn: (key) =>
      apiFetch<LicenseInfo>("/api/evidence/license/activate", {
        method: "POST",
        body: JSON.stringify({ key }),
      }),
    onSuccess: (data) => {
      qc.setQueryData(["license"], data);
      qc.invalidateQueries({ queryKey: ["evidence-preview"] });
      setKeyText("");
    },
  });

  const clearKey = useMutation({
    mutationFn: () => apiFetch("/api/evidence/license/clear", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["license"] });
      qc.invalidateQueries({ queryKey: ["evidence-preview"] });
    },
  });

  const exportJson = useMutation({
    mutationFn: async () => {
      const pack = await apiFetch<Record<string, unknown>>("/api/evidence/pack");
      downloadText("homeupdater-evidence.json", JSON.stringify(pack, null, 2), "application/json");
      return pack;
    },
  });

  const exportCsv = useMutation({
    mutationFn: async () => {
      const csv = await apiFetchText("/api/evidence/pack.csv");
      downloadText("homeupdater-evidence.csv", csv, "text/csv");
      return csv;
    },
  });

  const buildRollup = useMutation<Rollup, Error, unknown[]>({
    mutationFn: (packs) =>
      apiFetch<Rollup>("/api/evidence/rollup", {
        method: "POST",
        body: JSON.stringify({ packs }),
      }),
    onSuccess: (data) => setRollup(data),
  });

  const rollupCsv = useMutation<string, Error, unknown[]>({
    mutationFn: async (packs) => {
      const csv = await apiFetchText("/api/evidence/rollup.csv", {
        method: "POST",
        body: JSON.stringify({ packs }),
      });
      downloadText("homeupdater-rollup.csv", csv, "text/csv");
      return csv;
    },
  });

  const [pickedPacks, setPickedPacks] = useState<unknown[]>([]);
  const [readError, setReadError] = useState("");

  const onFiles = async (files: FileList | null) => {
    setReadError("");
    if (!files?.length) return;
    const parsed: unknown[] = [];
    for (const f of Array.from(files)) {
      try {
        parsed.push(JSON.parse(await f.text()));
      } catch {
        // A file that isn't a pack is named, not silently dropped — a partner must
        // know which input was ignored.
        setReadError(t("pages.evidence.rollup.badFile", { name: f.name }));
      }
    }
    setPickedPacks(parsed);
  };

  const lic = license.data;
  const licensed = !!lic?.can_export_evidence;
  const isPartner = licensed && lic?.tier === "partner";
  const pv = preview.data;

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      {/* header */}
      <div className="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <button type="button" onClick={onBack} className="btn-secondary inline-flex items-center gap-2">
          <BackIcon className="w-4 h-4" />
          <span className="hidden sm:inline">{t("nav.dashboard")}</span>
        </button>
        <div className="flex items-center gap-2">
          <FileCheck2 className="w-5 h-5 text-primary" />
          <div>
            <h2 className="text-xl font-display font-bold leading-tight">
              {t("pages.evidence.title")}
            </h2>
            <p className="text-xs text-fg-muted">{t("pages.evidence.subtitle")}</p>
          </div>
        </div>
        <div className="w-20" />
      </div>

      {/* الترخيص */}
      <section className="card mb-5">
        <div className="flex items-center gap-2 mb-3">
          <KeyRound className="w-4 h-4 text-primary" />
          <h3 className="font-display font-bold">{t("pages.evidence.license.title")}</h3>
        </div>

        {lic && (
          <div className="flex items-center gap-2 flex-wrap mb-3">
            <span
              className={cn(
                "text-xs px-2 py-0.5 rounded-full border inline-flex items-center gap-1",
                licensed
                  ? "border-success/40 bg-success/10 text-success"
                  : "border-border bg-surface-2 text-fg-muted",
              )}
            >
              {licensed ? <ShieldCheck className="w-3 h-3" /> : <ShieldX className="w-3 h-3" />}
              {licensed
                ? t("pages.evidence.license.active", { tier: lic.tier })
                : t(`pages.evidence.license.reason.${lic.reason || "none"}`, lic.reason || "none")}
            </span>
            {lic.licensee && <span className="text-sm text-fg-muted">{lic.licensee}</span>}
            {lic.expires && (
              <span className="text-xs text-fg-subtle">
                {t("pages.evidence.license.expires", { date: lic.expires })}
              </span>
            )}
          </div>
        )}

        <div className="flex items-center gap-2 flex-wrap">
          <input
            type="text"
            dir="ltr"
            value={keyText}
            onChange={(e) => setKeyText(e.target.value)}
            placeholder="HU1.…"
            aria-label={t("pages.evidence.license.keyLabel")}
            className="input flex-1 min-w-[240px] font-mono text-xs"
          />
          <button
            type="button"
            onClick={() => activate.mutate(keyText.trim())}
            disabled={activate.isPending || keyText.trim().length < 8}
            className="btn-primary inline-flex items-center gap-2"
          >
            {activate.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <KeyRound className="w-4 h-4" />
            )}
            {t("pages.evidence.license.activate")}
          </button>
          {licensed && (
            <button
              type="button"
              onClick={() => clearKey.mutate()}
              disabled={clearKey.isPending}
              className="btn-secondary text-danger"
            >
              {t("pages.evidence.license.clear")}
            </button>
          )}
        </div>
        {activate.isError && (
          <p className="text-sm text-danger mt-2">
            {t("pages.evidence.license.failed")} {activate.error.message}
          </p>
        )}
        <p className="text-xs text-fg-subtle mt-2">{t("pages.evidence.license.freeNote")}</p>
      </section>

      {/* المعاينة المجانية + التصدير */}
      <section className="card mb-5">
        <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
          <div className="flex items-center gap-2">
            <FileCheck2 className="w-4 h-4 text-primary" />
            <h3 className="font-display font-bold">{t("pages.evidence.pack.title")}</h3>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => exportJson.mutate()}
              disabled={!licensed || exportJson.isPending}
              title={!licensed ? t("pages.evidence.pack.needLicense") : undefined}
              className="btn-secondary inline-flex items-center gap-2"
            >
              {exportJson.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Download className="w-4 h-4" />
              )}
              JSON
            </button>
            <button
              type="button"
              onClick={() => exportCsv.mutate()}
              disabled={!licensed || exportCsv.isPending}
              title={!licensed ? t("pages.evidence.pack.needLicense") : undefined}
              className="btn-primary inline-flex items-center gap-2"
            >
              {exportCsv.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Download className="w-4 h-4" />
              )}
              CSV
            </button>
          </div>
        </div>

        {preview.isLoading && (
          <p className="text-sm text-fg-muted inline-flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" /> {t("status.loading")}
          </p>
        )}

        {pv && (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
              <Metric label={t("pages.evidence.pack.devices")} value={pv.inventory_total} />
              <Metric
                label={t("pages.evidence.pack.coverage")}
                value={`${pv.coverage.percent}%`}
                hint={t("pages.evidence.pack.coverageHint", {
                  mapped: pv.coverage.mapped,
                  total: pv.coverage.total,
                })}
              />
              <Metric
                label={t("pages.evidence.pack.findings")}
                value={pv.findings_total}
                tone={pv.findings_total > 0 ? "danger" : "ok"}
              />
              <Metric
                label={t("pages.evidence.pack.chain")}
                value={pv.audit.chain_ok ? t("pages.evidence.pack.chainOk") : t("pages.evidence.pack.chainBroken")}
                tone={pv.audit.chain_ok ? "ok" : "danger"}
                hint={t("pages.evidence.pack.entries", { n: pv.audit.entries })}
              />
            </div>

            {!pv.audit.chain_ok && (
              <div className="card mb-3 flex items-start gap-2 text-sm border-danger/40 bg-danger/10">
                <AlertTriangle className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
                <span>
                  {t("pages.evidence.pack.chainBrokenWarn", { seq: pv.audit.broken_at ?? "—" })}
                </span>
              </div>
            )}

            {/* الصدق في العرض: ماذا لا تُثبِته البصمة، وماذا تعني «لا نتائج» */}
            <div className="card flex items-start gap-2 text-xs border-info/30 bg-info/5">
              <Info className="w-4 h-4 text-info flex-shrink-0 mt-0.5" />
              <div className="text-fg-muted">
                <p>{t("pages.evidence.pack.stampNote")}</p>
                <p className="mt-1">{t("pages.evidence.pack.limitsNote")}</p>
              </div>
            </div>
          </>
        )}
      </section>

      {/* تجميع الشركاء */}
      <section className="card">
        <div className="flex items-center gap-2 mb-1">
          <Users className="w-4 h-4 text-primary" />
          <h3 className="font-display font-bold">{t("pages.evidence.rollup.title")}</h3>
        </div>
        <p className="text-xs text-fg-muted mb-3">{t("pages.evidence.rollup.hint")}</p>

        {!isPartner && (
          <p className="text-sm text-fg-muted">{t("pages.evidence.rollup.needPartner")}</p>
        )}

        {isPartner && (
          <>
            <div className="flex items-center gap-2 flex-wrap">
              <input
                ref={fileInput}
                type="file"
                accept=".json,application/json"
                multiple
                onChange={(e) => onFiles(e.target.files)}
                aria-label={t("pages.evidence.rollup.pick")}
                className="text-xs"
              />
              <button
                type="button"
                onClick={() => buildRollup.mutate(pickedPacks)}
                disabled={buildRollup.isPending || pickedPacks.length === 0}
                className="btn-primary inline-flex items-center gap-2"
              >
                {buildRollup.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Upload className="w-4 h-4" />
                )}
                {t("pages.evidence.rollup.build", { n: pickedPacks.length })}
              </button>
              {rollup && (
                <button
                  type="button"
                  onClick={() => rollupCsv.mutate(pickedPacks)}
                  disabled={rollupCsv.isPending}
                  className="btn-secondary inline-flex items-center gap-2"
                >
                  <Download className="w-4 h-4" /> CSV
                </button>
              )}
            </div>
            {readError && <p className="text-sm text-warning mt-2">{readError}</p>}
            {buildRollup.isError && (
              <p className="text-sm text-danger mt-2">
                {(buildRollup.error as ApiError).message}
              </p>
            )}

            {rollup && (
              <div className="mt-4">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
                  <Metric
                    label={t("pages.evidence.rollup.sites")}
                    value={rollup.totals.sites_verified}
                  />
                  <Metric
                    label={t("pages.evidence.rollup.devices")}
                    value={rollup.totals.products}
                  />
                  <Metric
                    label={t("pages.evidence.rollup.findings")}
                    value={rollup.totals.findings}
                    tone={rollup.totals.findings > 0 ? "danger" : "ok"}
                  />
                  <Metric
                    label={t("pages.evidence.rollup.avgCoverage")}
                    value={`${rollup.totals.avg_coverage_percent}%`}
                  />
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-fg-muted border-b border-border">
                        <th className="text-start py-1">{t("pages.evidence.rollup.thSite")}</th>
                        <th className="text-start py-1">{t("pages.evidence.rollup.thDevices")}</th>
                        <th className="text-start py-1">{t("pages.evidence.rollup.thCoverage")}</th>
                        <th className="text-start py-1">{t("pages.evidence.rollup.thFindings")}</th>
                        <th className="text-start py-1">{t("pages.evidence.rollup.thChain")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rollup.sites.map((s) => (
                        <tr key={s.stamp} className="border-b border-border last:border-0">
                          <td className="py-1">{s.site}</td>
                          <td className="py-1">{s.inventory_total}</td>
                          <td className="py-1">{s.coverage_percent}%</td>
                          <td className={cn("py-1", s.findings_total > 0 && "text-danger font-bold")}>
                            {s.findings_total}
                          </td>
                          <td className="py-1">
                            {s.chain_ok ? (
                              <span className="text-success">✓</span>
                            ) : (
                              <span className="text-danger font-bold">
                                {t("pages.evidence.rollup.chainBroken")}
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* الحزم المرفوضة تُعرَض دائمًا — إخفاؤها يمنح التزوير مصداقية المجموع */}
                {rollup.rejected.length > 0 && (
                  <div className="card mt-3 border-danger/40 bg-danger/10">
                    <p className="text-sm font-bold text-danger inline-flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4" />
                      {t("pages.evidence.rollup.rejected", { n: rollup.rejected.length })}
                    </p>
                    <p className="text-xs text-fg-muted mt-1">
                      {t("pages.evidence.rollup.rejectedHint")}
                    </p>
                    <ul className="text-xs mt-2 space-y-0.5">
                      {rollup.rejected.map((r) => (
                        <li key={r.index}>
                          #{r.index + 1} —{" "}
                          {t(`pages.evidence.rollup.reason.${r.reason}`, r.reason)}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "ok" | "danger";
}) {
  return (
    <div className="bg-surface-2 rounded-lg p-3">
      <p className="text-xs text-fg-muted">{label}</p>
      <p
        className={cn(
          "text-lg font-bold font-mono",
          tone === "danger" && "text-danger",
          tone === "ok" && "text-success",
        )}
      >
        {value}
      </p>
      {hint && <p className="text-[11px] text-fg-subtle">{hint}</p>}
    </div>
  );
}
