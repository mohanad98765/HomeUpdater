import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  Loader2,
  RefreshCw,
  ShieldCheck,
  ExternalLink,
  AlertTriangle,
  HelpCircle,
  PackageSearch,
  Boxes,
} from "lucide-react";
import { apiFetch, cn } from "@/lib/utils";

// ================================================================
// النتائج الدقيقة (CPE) — تُطابَق بالمنتج والإصدار المثبَّت لا باسم المصنّع.
// الفكرة الحاكمة في هذا العرض: كل ما لا نستطيع إثباته يُقال صريحًا —
//   • ما لا يُطابَق يظهر بسببه (لا مخفيًّا)،
//   • ونسبة التغطية معروضة دائمًا،
//   • والنتائج «الفضفاضة» (سجلّات NVD بلا حدود إصدار) مفصولة ومُعلَّمة.
// ================================================================

interface Range {
  precision?: string;
  start_including?: string | null;
  start_excluding?: string | null;
  end_including?: string | null;
  end_excluding?: string | null;
}
interface Cve {
  id: string;
  score: number;
  severity: string;
  published: string;
  description: string;
  url: string;
  applies_because?: Range | null;
  /** Only on records we deliberately do NOT count: why they were set aside. */
  precision?: "unbounded" | "not_vulnerable" | "scheme_mismatch";
}
interface Matched {
  product_id: string;
  name: string;
  version: string;
  reported_version: string;
  cpe_name: string;
  confidence: string;
  caveat: string;
  total_results: number;
  cves: Cve[];
  broad_matches: Cve[];
  fetched_at: string | null;
}
interface Unmatched {
  product_id: string;
  name: string;
  version: string;
  reason: string;
  detail?: string;
}
interface Precise {
  match_mode: string;
  matched: Matched[];
  unmatched: Unmatched[];
  coverage: {
    total: number;
    mapped: number;
    unmapped: number;
    percent: number;
  };
}

const SEV_CLASS: Record<string, string> = {
  CRITICAL: "bg-danger/15 text-danger border-danger/30",
  HIGH: "bg-warning/15 text-warning border-warning/30",
  MEDIUM: "bg-info/15 text-info border-info/30",
  LOW: "bg-surface-2 text-fg-muted border-border",
};

/** "يؤثّر على ما قبل 26.03" — يجعل النتيجة قابلة للمراجعة لا مجرّد تصديق. */
function rangeText(
  r: Range | null | undefined,
  t: (k: string, o?: object) => string,
): string {
  if (!r) return "";
  const parts: string[] = [];
  if (r.start_including)
    parts.push(t("pages.sec.precise.fromIncl", { v: r.start_including }));
  if (r.start_excluding)
    parts.push(t("pages.sec.precise.fromExcl", { v: r.start_excluding }));
  if (r.end_including)
    parts.push(t("pages.sec.precise.toIncl", { v: r.end_including }));
  if (r.end_excluding)
    parts.push(t("pages.sec.precise.toExcl", { v: r.end_excluding }));
  return parts.join(" · ");
}

export function PreciseFindings() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [showUnmatched, setShowUnmatched] = useState(false);

  const precise = useQuery<Precise>({
    queryKey: ["precise"],
    queryFn: () => apiFetch<Precise>("/api/security/precise"),
  });

  const scanInventory = useMutation({
    mutationFn: () =>
      apiFetch("/api/updates/inventory/refresh", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["precise"] }),
  });

  const checkNvd = useMutation<Precise, Error>({
    mutationFn: () =>
      apiFetch<Precise>("/api/security/precise?refresh_nvd=true"),
    onSuccess: (data) => qc.setQueryData(["precise"], data),
  });

  const data = precise.data;
  const cov = data?.coverage;
  const withFindings = (data?.matched ?? []).filter((m) => m.cves.length > 0);
  const clean = (data?.matched ?? []).filter((m) => m.cves.length === 0);

  return (
    <div>
      {/* شريط الإجراءات */}
      <div className="card mb-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <PackageSearch className="w-4 h-4 text-primary" />
            <div>
              <h3 className="font-bold">{t("pages.sec.precise.title")}</h3>
              <p className="text-xs text-fg-muted">
                {t("pages.sec.precise.subtitle")}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <button
              type="button"
              onClick={() => scanInventory.mutate()}
              disabled={scanInventory.isPending}
              className="btn-secondary inline-flex items-center gap-2"
            >
              {scanInventory.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Boxes className="w-4 h-4" />
              )}
              {t("pages.sec.precise.scanInventory")}
            </button>
            <button
              type="button"
              onClick={() => checkNvd.mutate()}
              disabled={checkNvd.isPending || (cov?.mapped ?? 0) === 0}
              title={
                (cov?.mapped ?? 0) === 0
                  ? t("pages.sec.precise.needInventory")
                  : undefined
              }
              className="btn-primary inline-flex items-center gap-2"
            >
              {checkNvd.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4" />
              )}
              {checkNvd.isPending
                ? t("pages.sec.precise.checking")
                : t("pages.sec.precise.checkNvd")}
            </button>
          </div>
        </div>

        {/* التغطية — تُعرَض دائمًا حتى لا يُوحي التقرير بشمولٍ لا يملكه */}
        {cov && (
          <p className="text-xs text-fg-muted mt-3">
            {t("pages.sec.precise.coverage", {
              mapped: cov.mapped,
              total: cov.total,
              percent: cov.percent,
            })}
          </p>
        )}
        {checkNvd.isError && (
          <p className="text-sm text-danger mt-2">
            {t("pages.sec.precise.failed")} {checkNvd.error.message}
          </p>
        )}
      </div>

      {precise.isLoading && (
        <p className="text-sm text-fg-muted inline-flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> {t("status.loading")}
        </p>
      )}

      {data && data.coverage.total === 0 && (
        <div className="card text-center text-sm text-fg-muted">
          {t("pages.sec.precise.emptyInventory")}
        </div>
      )}

      {/* منتجات لها ثغرات مؤكَّدة على الإصدار المثبَّت */}
      {withFindings.map((m) => (
        <div key={m.product_id} className="card mb-3">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="min-w-0">
              <h4 className="font-bold">{m.name}</h4>
              <p className="text-xs font-mono text-fg-muted break-all">
                {m.cpe_name}
              </p>
              {m.reported_version !== m.version && (
                <p className="text-xs text-fg-subtle">
                  {t("pages.sec.precise.trimmed", {
                    reported: m.reported_version,
                    used: m.version,
                  })}
                </p>
              )}
            </div>
            <div className="flex items-center gap-2">
              {m.confidence === "medium" && (
                <span className="text-xs px-2 py-0.5 rounded-full border border-warning/40 bg-warning/10 text-warning">
                  {t("pages.sec.precise.mediumConfidence")}
                </span>
              )}
              <span className="text-xs px-2 py-0.5 rounded-full border border-danger/30 bg-danger/10 text-danger">
                {t("pages.sec.precise.affected", { count: m.cves.length })}
              </span>
            </div>
          </div>

          {m.caveat && (
            <p className="text-xs text-fg-muted mt-2 italic">{m.caveat}</p>
          )}

          <ul className="mt-3 space-y-2">
            {m.cves.map((c) => (
              <li key={c.id} className="border border-border rounded-md p-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className={cn(
                      "text-xs px-2 py-0.5 rounded-full border font-bold",
                      SEV_CLASS[c.severity] ?? SEV_CLASS.LOW,
                    )}
                  >
                    {c.severity || "—"} {c.score ? c.score.toFixed(1) : ""}
                  </span>
                  <a
                    href={c.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-mono text-sm text-primary hover:underline inline-flex items-center gap-1"
                  >
                    {c.id} <ExternalLink className="w-3 h-3" />
                  </a>
                  {c.applies_because && (
                    <span className="text-xs text-fg-muted">
                      — {t("pages.sec.precise.appliesBecause")}{" "}
                      {rangeText(c.applies_because, t as never)}
                    </span>
                  )}
                </div>
                {c.description && (
                  <p className="text-xs text-fg-muted mt-1 line-clamp-2">
                    {c.description}
                  </p>
                )}
              </li>
            ))}
          </ul>

          {/* النتائج الفضفاضة: سجلّات NVD بلا حدود إصدار — ليست دليلًا على هذا البناء */}
          {m.broad_matches.length > 0 && (
            <div className="mt-3 p-2 rounded-md border border-warning/30 bg-warning/5">
              <p className="text-xs text-warning font-bold mb-1">
                <AlertTriangle className="w-3 h-3 inline" />{" "}
                {t("pages.sec.precise.broadTitle", {
                  count: m.broad_matches.length,
                })}
              </p>
              <p className="text-xs text-fg-muted mb-1">
                {t("pages.sec.precise.broadHint")}
              </p>
              <ul className="space-y-1">
                {m.broad_matches.map((c) => (
                  <li key={c.id} className="text-xs">
                    <a
                      href={c.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-mono text-fg-muted hover:text-fg underline"
                    >
                      {c.id}
                    </a>
                    {/* لماذا لم تُحتسَب: يُقال صريحًا لكل سجلّ، لا يُخفى */}
                    <span className="text-fg-muted">
                      {" "}
                      —{" "}
                      {t(
                        `pages.sec.precise.notCounted.${c.precision || "unbounded"}`,
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ))}

      {/* منتجات فُحصت ولم تظهر لها ثغرة على هذا الإصدار */}
      {clean.length > 0 && (
        <div className="card mb-3">
          <p className="text-sm font-bold inline-flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-success" />
            {t("pages.sec.precise.cleanTitle", { count: clean.length })}
          </p>
          <p className="text-xs text-fg-muted mt-1">
            {t("pages.sec.precise.cleanHint")}
          </p>
          <div className="flex flex-wrap gap-2 mt-2">
            {clean.map((m) => (
              <span
                key={m.product_id}
                className="text-xs px-2 py-0.5 rounded-full border border-border text-fg-muted"
              >
                {m.name} {m.version}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* غير المُطابَق — يُعرَض بسببه، فالصمت هنا تضليل */}
      {(data?.unmatched?.length ?? 0) > 0 && (
        <div className="card">
          <button
            type="button"
            onClick={() => setShowUnmatched((v) => !v)}
            className="text-sm font-bold inline-flex items-center gap-2"
            aria-expanded={showUnmatched}
          >
            <HelpCircle className="w-4 h-4 text-fg-muted" />
            {t("pages.sec.precise.unmatchedTitle", {
              count: data!.unmatched.length,
            })}
          </button>
          <p className="text-xs text-fg-muted mt-1">
            {t("pages.sec.precise.unmatchedHint")}
          </p>
          {showUnmatched && (
            <ul className="mt-3 space-y-1">
              {data!.unmatched.map((u) => (
                <li
                  key={u.product_id}
                  className="text-xs border-b border-border pb-1"
                >
                  <span className="font-mono">{u.product_id}</span>{" "}
                  <span className="text-fg-muted">{u.version}</span>
                  <span className="ms-2 px-1.5 py-0.5 rounded border border-border text-fg-subtle">
                    {t(`pages.sec.precise.reason.${u.reason}`, u.reason)}
                  </span>
                  {u.detail && (
                    <p className="text-fg-subtle mt-0.5">{u.detail}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
