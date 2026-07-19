import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  ArrowRight,
  Loader2,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  ExternalLink,
  Info,
  Search,
} from "lucide-react";
import { apiFetch, cn } from "@/lib/utils";
import { useLanguage } from "@/lib/language";

// ================================================================
// صفحة الأمان — الثغرات المعروفة لكل جهاز (حسب المصنّع، من NVD)
// ================================================================

interface DeviceCVE {
  device_id: number;
  display_name: string;
  ip: string;
  vendor: string;
  cve_total: number | null;
  top_severity: string | null;
  checked: boolean;
}
interface Overview {
  devices: DeviceCVE[];
  vendors_total: number;
  vendors_checked: number;
}
interface CVEItem {
  id: string;
  score: number;
  severity: string;
  published: string;
  description: string;
  url: string;
}
interface CVESummary {
  keyword: string;
  total_results: number;
  cves: CVEItem[];
  fetched_at: string | null;
  cached: boolean;
}

const sevBadge = (s: string | null) =>
  s === "CRITICAL"
    ? "badge-danger"
    : s === "HIGH"
      ? "badge-warning"
      : s === "MEDIUM"
        ? "badge-info"
        : "";

const sevLabel: Record<string, string> = {
  CRITICAL: "حرجة",
  HIGH: "عالية",
  MEDIUM: "متوسطة",
  LOW: "منخفضة",
};

export function SecurityPage({ onBack }: { onBack: () => void }) {
  const { t } = useTranslation();
  const { dir } = useLanguage();
  const qc = useQueryClient();
  const BackIcon = dir === "rtl" ? ArrowRight : ArrowLeft;

  const overview = useQuery<Overview>({
    queryKey: ["security-overview"],
    queryFn: () => apiFetch<Overview>("/api/security/overview"),
  });

  const refresh = useMutation({
    mutationFn: () =>
      apiFetch("/api/security/refresh", { method: "POST", body: JSON.stringify({}) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["security-overview"] }),
  });

  // فحص يدوي: اكتب أي مصنّع/كلمة (TP-Link، Cisco…) وافحصه مباشرة — يعمل دائماً
  const [keyword, setKeyword] = useState("");
  const manual = useMutation<CVESummary, Error, string>({
    mutationFn: (kw) =>
      apiFetch<CVESummary>(`/api/security/cves?keyword=${encodeURIComponent(kw)}`),
  });
  const runManual = () => {
    const kw = keyword.trim();
    if (kw) manual.mutate(kw);
  };

  const devices = overview.data?.devices ?? [];
  const withVendor = useMemo(() => devices.filter((d) => d.vendor), [devices]);
  const flagged = useMemo(() => withVendor.filter((d) => (d.cve_total ?? 0) > 0), [withVendor]);

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      {/* Top bar */}
      <div className="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <button type="button" onClick={onBack} className="btn-secondary inline-flex items-center gap-2">
          <BackIcon className="w-4 h-4" />
          <span className="hidden sm:inline">{t("nav.dashboard")}</span>
        </button>
        <div>
          <h2 className="text-xl font-display font-bold">الأمان — الثغرات المعروفة</h2>
          <p className="text-xs text-fg-muted">Security · known vulnerabilities (NVD)</p>
        </div>
        <button
          type="button"
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending || withVendor.length === 0}
          title={
            withVendor.length === 0
              ? "افحص الشبكة أولاً من صفحة «الأجهزة» ليظهر مصنّعو الأجهزة، أو استخدم «الفحص اليدوي» بالأسفل"
              : "فحص ثغرات كل مصنّعي الأجهزة المكتشفة"
          }
          className="btn-primary inline-flex items-center gap-2"
        >
          {refresh.isPending ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              جارٍ الفحص…
            </>
          ) : (
            <>
              <RefreshCw className="w-4 h-4" />
              فحص الثغرات
            </>
          )}
        </button>
      </div>

      {/* Explanation */}
      <div className="card mb-6 flex items-start gap-3 text-sm border-info/30 bg-info/5">
        <Info className="w-5 h-5 text-info flex-shrink-0 mt-0.5" />
        <div className="text-fg-muted">
          تُطابَق الثغرات حسب <span className="font-semibold text-fg">مصنّع</span> الجهاز (لا الإصدار
          الدقيق)، من قاعدة <span dir="ltr">NVD</span> الرسمية. الأرقام إرشادية للتوعية الأمنية —
          افتح رابط <span dir="ltr">NVD</span> لتفاصيل كل ثغرة. أوّل فحص قد يستغرق دقيقة (حدود معدّل NVD)،
          ثم يُخزَّن مؤقتاً 24 ساعة.
        </div>
      </div>

      {/* فحص يدوي — يعمل دائماً بلا حاجة لمسح الشبكة */}
      <div className="card mb-6">
        <div className="flex items-center gap-2 mb-1">
          <Search className="w-4 h-4 text-primary" />
          <h3 className="font-bold">فحص يدوي لأي مصنّع</h3>
        </div>
        <p className="text-xs text-fg-muted mb-3">
          اكتب اسم أي مصنّع أو منتج (مثل <span dir="ltr">TP-Link</span>، <span dir="ltr">Cisco</span>،{" "}
          <span dir="ltr">Samsung</span>، <span dir="ltr">iPhone</span>) وافحص ثغراته مباشرة من{" "}
          <span dir="ltr">NVD</span> — دون الحاجة لمسح الشبكة.
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          <input
            type="text"
            dir="ltr"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runManual()}
            placeholder="TP-Link، Cisco، Samsung…"
            className="flex-1 min-w-[200px] px-3 py-2 rounded-md border border-border bg-bg text-fg focus:border-primary focus:outline-none font-mono"
          />
          <button
            type="button"
            onClick={runManual}
            disabled={manual.isPending || keyword.trim().length === 0}
            className="btn-primary inline-flex items-center gap-2"
          >
            {manual.isPending ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" /> جارٍ الفحص…
              </>
            ) : (
              <>
                <Search className="w-4 h-4" /> فحص
              </>
            )}
          </button>
        </div>

        {manual.isError && (
          <div className="mt-3 p-3 rounded-md border border-danger/30 bg-danger/10 text-danger text-sm">
            تعذّر الفحص: {manual.error.message}
          </div>
        )}

        {manual.data && (
          <div className="mt-4">
            <div className="text-sm mb-2">
              نتائج <span className="font-bold" dir="ltr">{manual.data.keyword}</span>:{" "}
              <span className="font-mono font-bold text-warning">
                {manual.data.total_results.toLocaleString()}
              </span>{" "}
              ثغرة معروفة إجمالاً
              {manual.data.cached && <span className="text-fg-subtle text-xs"> (من الكاش)</span>}
            </div>
            {manual.data.cves.length === 0 ? (
              <p className="text-sm text-success inline-flex items-center gap-1">
                <ShieldCheck className="w-4 h-4" /> لا نتائج مطابقة.
              </p>
            ) : (
              <ul className="divide-y divide-border border border-border rounded-lg overflow-hidden">
                {manual.data.cves.map((c) => (
                  <li key={c.id} className="p-3 hover:bg-surface-2/50">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <a
                        href={c.url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="font-mono text-sm text-primary hover:underline inline-flex items-center gap-1"
                        dir="ltr"
                      >
                        {c.id} <ExternalLink className="w-3 h-3" />
                      </a>
                      <div className="flex items-center gap-2">
                        {c.severity && (
                          <span className={cn("badge", sevBadge(c.severity))}>
                            {sevLabel[c.severity] || c.severity}
                            {c.score > 0 && ` · ${c.score.toFixed(1)}`}
                          </span>
                        )}
                        <span className="text-xs text-fg-subtle font-mono">{c.published}</span>
                      </div>
                    </div>
                    {c.description && (
                      <p className="mt-1 text-xs text-fg-muted line-clamp-2" dir="ltr">
                        {c.description}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
        <Stat icon={ShieldCheck} label="أجهزة لها مصنّع معروف" value={withVendor.length} accent="info" />
        <Stat
          icon={ShieldAlert}
          label="أجهزة عليها ثغرات معروفة"
          value={flagged.length}
          accent={flagged.length > 0 ? "warning" : "success"}
        />
        <Stat
          icon={RefreshCw}
          label="مصنّعون مفحوصون"
          value={`${overview.data?.vendors_checked ?? 0}/${overview.data?.vendors_total ?? 0}`}
          accent="primary"
        />
      </div>

      {refresh.isError && (
        <div className="mb-6 p-4 rounded-lg border border-danger/30 bg-danger/10 text-danger text-sm">
          تعذّر الفحص:{" "}
          {refresh.error instanceof Error ? refresh.error.message : "خطأ غير معروف"}
        </div>
      )}

      {/* List */}
      {overview.isLoading ? (
        <div className="card text-center py-12">
          <Loader2 className="w-8 h-8 animate-spin mx-auto mb-3 text-fg-muted" />
        </div>
      ) : withVendor.length === 0 ? (
        <div className="card text-center py-16">
          <ShieldCheck className="w-12 h-12 text-fg-subtle mx-auto mb-3" />
          <p className="text-fg-muted">
            لا توجد أجهزة بمصنّع معروف بعد. افحص الشبكة أولاً من صفحة «الأجهزة».
          </p>
        </div>
      ) : (
        <div className="card !p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-2 text-xs font-bold text-fg-muted">
                <tr>
                  <th className="px-4 py-3 text-start">الجهاز</th>
                  <th className="px-4 py-3 text-start">المصنّع</th>
                  <th className="px-4 py-3 text-start">أعلى خطورة</th>
                  <th className="px-4 py-3 text-start">ثغرات معروفة</th>
                  <th className="px-4 py-3 text-start">NVD</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {withVendor.map((d) => (
                  <tr key={d.device_id} className={cn((d.cve_total ?? 0) > 0 && "bg-warning/5")}>
                    <td className="px-4 py-3">
                      <div className="font-medium truncate max-w-[220px]" title={d.display_name}>
                        {d.display_name}
                      </div>
                      <div className="text-xs text-fg-muted font-mono" dir="ltr">
                        {d.ip}
                      </div>
                    </td>
                    <td className="px-4 py-3">{d.vendor}</td>
                    <td className="px-4 py-3">
                      {d.checked && d.top_severity ? (
                        <span className={cn("badge", sevBadge(d.top_severity))}>
                          {sevLabel[d.top_severity] || d.top_severity}
                        </span>
                      ) : d.checked ? (
                        <span className="text-success text-xs">— نظيف</span>
                      ) : (
                        <span className="text-fg-subtle text-xs">لم يُفحص</span>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono tabular-nums">
                      {d.checked ? (d.cve_total ?? 0).toLocaleString() : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <a
                        href={`https://nvd.nist.gov/vuln/search/results?query=${encodeURIComponent(d.vendor)}`}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="inline-flex items-center gap-1 text-primary hover:underline text-xs"
                      >
                        فتح <ExternalLink className="w-3 h-3" />
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
  accent,
}: {
  icon: typeof ShieldAlert;
  label: string;
  value: string | number;
  accent: "primary" | "success" | "warning" | "info";
}) {
  const colors: Record<string, string> = {
    primary: "bg-primary/10 text-primary",
    success: "bg-success/10 text-success",
    warning: "bg-warning/10 text-warning",
    info: "bg-info/10 text-info",
  };
  return (
    <div className="card !p-4 flex items-center gap-3">
      <div className={cn("w-10 h-10 rounded-lg flex items-center justify-center", colors[accent])}>
        <Icon className="w-5 h-5" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-xs text-fg-muted truncate">{label}</div>
        <div className="text-xl font-display font-bold tabular-nums">{value}</div>
      </div>
    </div>
  );
}
