import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ArrowLeft, ArrowRight, Loader2, Sparkles, Cpu, KeyRound } from "lucide-react";
import { apiFetch } from "@/lib/utils";
import { useLanguage } from "@/lib/language";

// ================================================================
// صفحة المستشار الذكي — تحليل agentic عبر Claude لأولويات التحديث
// ================================================================

interface AdvisorStatus {
  configured: boolean;
  model: string;
  env: boolean;
}
interface AdvisorResult {
  recommendations: string;
  trace: { tool: string }[];
  model: string;
  truncated?: boolean;
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
  const qc = useQueryClient();
  const BackIcon = dir === "rtl" ? ArrowRight : ArrowLeft;
  const [keyInput, setKeyInput] = useState("");

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

  const saveKey = useMutation({
    mutationFn: () =>
      apiFetch("/api/advisor/key", { method: "POST", body: JSON.stringify({ key: keyInput.trim() }) }),
    onSuccess: () => {
      setKeyInput("");
      qc.invalidateQueries({ queryKey: ["advisor-status"] });
    },
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
          <div>
            <div className="flex items-center gap-2 mb-2">
              <KeyRound className="w-4 h-4 text-primary" />
              <label className="text-sm font-medium">{t("pages.advisor.keyLabel")}</label>
            </div>
            <p className="text-xs text-fg-muted mb-2">{t("pages.advisor.keyHint")}</p>
            <div className="flex items-center gap-2 flex-wrap">
              <input
                type="password"
                dir="ltr"
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                placeholder="sk-ant-…"
                className="input flex-1 min-w-[220px]"
              />
              <button
                type="button"
                onClick={() => saveKey.mutate()}
                disabled={saveKey.isPending || keyInput.trim().length < 8}
                className="btn-primary inline-flex items-center gap-2"
              >
                {saveKey.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <KeyRound className="w-4 h-4" />}
                {t("pages.advisor.saveKey")}
              </button>
            </div>
            {saveKey.isError && (
              <p className="mt-2 text-sm text-danger">{(saveKey.error as Error).message}</p>
            )}
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
          {analyze.data.truncated && (
            <div className="mb-3 text-xs text-warning">⚠ {t("pages.advisor.truncated")}</div>
          )}
          <div className="whitespace-pre-wrap text-sm leading-relaxed">{analyze.data.recommendations}</div>
          <div className="mt-4 pt-3 border-t border-border text-xs text-fg-subtle inline-flex items-center gap-1">
            <Sparkles className="w-3 h-3" /> {t("pages.advisor.poweredBy")} · {analyze.data.model}
          </div>
        </div>
      )}
    </div>
  );
}
