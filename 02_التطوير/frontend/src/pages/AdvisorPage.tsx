import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ArrowLeft, ArrowRight, Loader2, Sparkles, Cpu, KeyRound, Download, CheckCircle2 } from "lucide-react";
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
interface AdvisorAction {
  type: "app" | "windows";
  id: string;
  title: string;
  reason?: string;
}
interface AdvisorResult {
  recommendations: string;
  trace: { tool: string }[];
  model: string;
  truncated?: boolean;
  actions?: AdvisorAction[];
}
interface ApplyResult {
  applied: number;
  skipped: string[];
  app?: { installed: number; total: number } | null;
  windows?: { installed: number; total: number } | null;
}

// map the agent's tool names to their i18n label keys
const TOOL_LABEL: Record<string, string> = {
  list_devices: "toolListDevices",
  check_vulnerabilities: "toolCheckVulns",
  list_pending_updates: "toolPendingUpdates",
  set_plan: "toolSetPlan",
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

  // Defined before `analyze` so a new analysis can reset its stale result.
  const apply = useMutation<ApplyResult, Error, AdvisorAction[]>({
    mutationFn: (actions) =>
      apiFetch<ApplyResult>("/api/advisor/apply", {
        method: "POST",
        body: JSON.stringify({ actions }),
      }),
  });

  const analyze = useMutation<AdvisorResult, Error>({
    mutationFn: () =>
      apiFetch<AdvisorResult>("/api/advisor/analyze", {
        method: "POST",
        body: JSON.stringify({ lang: i18n.language }),
      }),
    // A fresh analysis produces a new plan — clear the previous apply result so
    // the old "Applied N" line + hidden button don't stick to the new plan.
    onMutate: () => apply.reset(),
  });

  const saveKey = useMutation({
    mutationFn: () =>
      apiFetch("/api/advisor/key", { method: "POST", body: JSON.stringify({ key: keyInput.trim() }) }),
    onSuccess: () => {
      setKeyInput("");
      qc.invalidateQueries({ queryKey: ["advisor-status"] });
    },
  });

  const topActions = (analyze.data?.actions ?? []).slice(0, 3);
  const applyTop = () => {
    if (topActions.length === 0) return;
    const list = topActions.map((a, i) => `${i + 1}. ${a.title}`).join("\n");
    if (window.confirm(`${t("pages.advisor.applyConfirm")}\n\n${list}`)) apply.mutate(topActions);
  };

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

      {/* one-click apply of the top prioritized (local, pending) updates */}
      {topActions.length > 0 && (
        <div className="card mt-4">
          <div className="flex items-center gap-2 mb-2">
            <Download className="w-4 h-4 text-primary" />
            <h3 className="font-bold text-sm">{t("pages.advisor.planTitle")}</h3>
          </div>
          <ol className="text-sm space-y-1 mb-3 ps-5 list-decimal">
            {topActions.map((a, i) => (
              <li key={i}>
                <span className="font-medium">{a.title}</span>
                {a.reason && <span className="text-fg-muted"> — {a.reason}</span>}
              </li>
            ))}
          </ol>
          {!apply.data ? (
            <button
              type="button"
              onClick={applyTop}
              disabled={apply.isPending}
              className="btn-primary inline-flex items-center gap-2"
            >
              {apply.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Download className="w-4 h-4" />
              )}
              {apply.isPending ? t("pages.advisor.applying") : t("pages.advisor.applyTop3")}
            </button>
          ) : (
            <div className="text-sm inline-flex items-center gap-2 text-success flex-wrap">
              <CheckCircle2 className="w-4 h-4" />
              {t("pages.advisor.applied", { count: apply.data.applied })}
              {apply.data.skipped.length > 0 && (
                <span className="text-fg-muted">
                  · {t("pages.advisor.applySkipped", { count: apply.data.skipped.length })}
                </span>
              )}
            </div>
          )}
          {apply.isError && (
            <p className="mt-2 text-sm text-danger">
              {t("pages.advisor.applyFailed")} {apply.error.message}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
