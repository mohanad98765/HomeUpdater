import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ArrowLeft, ArrowRight, Loader2, Sparkles, Cpu, AlertTriangle } from "lucide-react";
import { apiFetch } from "@/lib/utils";
import { useLanguage } from "@/lib/language";

// ================================================================
// صفحة المستشار الذكي — تحليل agentic عبر Claude لأولويات التحديث
// ================================================================

interface AdvisorStatus {
  configured: boolean;
  model: string;
}
interface AdvisorResult {
  recommendations: string;
  trace: { tool: string }[];
  model: string;
}

// map the agent's tool names to their i18n label keys
const TOOL_LABEL: Record<string, string> = {
  list_devices: "toolListDevices",
  check_vulnerabilities: "toolCheckVulns",
  list_pending_updates: "toolPendingUpdates",
};

export function AdvisorPage({ onBack }: { onBack: () => void }) {
  const { t, i18n } = useTranslation();
  const { dir } = useLanguage();
  const BackIcon = dir === "rtl" ? ArrowRight : ArrowLeft;

  const status = useQuery<AdvisorStatus>({
    queryKey: ["advisor-status"],
    queryFn: () => apiFetch<AdvisorStatus>("/api/advisor/status"),
  });

  const analyze = useMutation<AdvisorResult, Error>({
    mutationFn: () =>
      apiFetch<AdvisorResult>("/api/advisor/analyze", {
        method: "POST",
        body: JSON.stringify({ lang: i18n.language }),
      }),
  });

  const configured = !!status.data?.configured;

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      {/* header */}
      <div className="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <button type="button" onClick={onBack} className="btn-secondary inline-flex items-center gap-2">
          <BackIcon className="w-4 h-4" />
          <span className="hidden sm:inline">{t("nav.dashboard")}</span>
        </button>
        <div className="flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-primary" />
          <div>
            <h2 className="text-xl font-display font-bold leading-tight">{t("pages.advisor.title")}</h2>
            <p className="text-xs text-fg-muted">{t("pages.advisor.subtitle")}</p>
          </div>
        </div>
        <div className="w-20" />
      </div>

      {/* intro + call to action */}
      <div className="card mb-6">
        <p className="text-sm text-fg-muted mb-4">{t("pages.advisor.intro")}</p>
        {configured ? (
          <button
            type="button"
            onClick={() => analyze.mutate()}
            disabled={analyze.isPending}
            className="btn-primary inline-flex items-center gap-2"
          >
            {analyze.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            {analyze.isPending ? t("pages.advisor.analyzing") : t("pages.advisor.analyze")}
          </button>
        ) : (
          <div className="flex items-start gap-3 text-sm border border-warning/30 bg-warning/10 rounded-lg p-3">
            <AlertTriangle className="w-5 h-5 text-warning flex-shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold text-fg">{t("pages.advisor.notConfigured")}</div>
              <div className="text-fg-muted mt-1" dir="ltr">
                {t("pages.advisor.notConfiguredHow")}
              </div>
            </div>
          </div>
        )}
      </div>

      {analyze.isError && (
        <div className="mb-6 p-4 rounded-lg border border-danger/30 bg-danger/10 text-danger text-sm">
          {t("pages.advisor.failed")} {analyze.error.message}
        </div>
      )}

      {/* agentic steps — which local tools the model called */}
      {analyze.data && analyze.data.trace.length > 0 && (
        <div className="mb-4">
          <div className="text-xs font-bold text-fg-muted mb-2">{t("pages.advisor.steps")}</div>
          <div className="flex flex-wrap gap-2">
            {analyze.data.trace.map((s, i) => (
              <span key={i} className="badge badge-info inline-flex items-center gap-1">
                <Cpu className="w-3 h-3" /> {t(`pages.advisor.${TOOL_LABEL[s.tool] ?? "toolListDevices"}`)}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* recommendations */}
      {analyze.data && (
        <div className="card">
          <div className="whitespace-pre-wrap text-sm leading-relaxed">{analyze.data.recommendations}</div>
          <div className="mt-4 pt-3 border-t border-border text-xs text-fg-subtle inline-flex items-center gap-1">
            <Sparkles className="w-3 h-3" /> {t("pages.advisor.poweredBy")} · {analyze.data.model}
          </div>
        </div>
      )}
    </div>
  );
}
