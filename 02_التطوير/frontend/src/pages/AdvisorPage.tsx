import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  ArrowRight,
  Loader2,
  Sparkles,
  Cpu,
  KeyRound,
  Download,
  CheckCircle2,
  MessageSquare,
  Send,
  FileText,
  ShieldCheck,
} from "lucide-react";
import { apiFetch, cn, type ApiError } from "@/lib/utils";
import { useLanguage } from "@/lib/language";

// A 403 from analyze/chat means the T11 data-sharing consent hasn't been given
// (or was revoked). Detect it so we can open the consent modal instead of
// showing a raw "[object]" error.
function isConsentError(err: unknown): boolean {
  const e = err as ApiError | undefined;
  const detail = (e?.body as { detail?: { error?: string } } | undefined)?.detail;
  return e?.status === 403 && detail?.error === "consent_required";
}

// ================================================================
// صفحة المستشار الذكي — تحليل agentic عبر Claude لأولويات التحديث
// ================================================================

interface AdvisorStatus {
  configured: boolean;
  model: string;
  env: boolean;
  consented: boolean;
}
interface ConsentText {
  ar: string;
  en: string;
  consented: boolean;
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
  const [chatMsgs, setChatMsgs] = useState<{ role: "user" | "assistant"; content: string }[]>([]);
  const [chatInput, setChatInput] = useState("");
  // T11 — data-sharing consent gate: the modal shown before the first cloud call.
  const [showConsent, setShowConsent] = useState(false);

  const status = useQuery<AdvisorStatus>({
    queryKey: ["advisor-status"],
    queryFn: () => apiFetch<AdvisorStatus>("/api/advisor/status"),
  });

  const configured = !!status.data?.configured;
  const consented = configured && status.data?.consented === true;
  const needsConsent = configured && status.data?.consented === false;

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
    // Consent revoked mid-session (or never given) → open the gate, not an error.
    onError: (err) => {
      if (isConsentError(err)) setShowConsent(true);
    },
  });

  const saveKey = useMutation({
    mutationFn: () =>
      apiFetch("/api/advisor/key", { method: "POST", body: JSON.stringify({ key: keyInput.trim() }) }),
    onSuccess: () => {
      setKeyInput("");
      qc.invalidateQueries({ queryKey: ["advisor-status"] });
    },
  });

  const chat = useMutation<{ reply: string }, Error, { role: "user" | "assistant"; content: string }[]>({
    mutationFn: (msgs) =>
      apiFetch<{ reply: string }>("/api/advisor/chat", {
        method: "POST",
        body: JSON.stringify({ messages: msgs }),
      }),
    onSuccess: (data, msgs) => setChatMsgs([...msgs, { role: "assistant", content: data.reply }]),
    onError: (err) => {
      if (isConsentError(err)) setShowConsent(true);
    },
  });
  const sendChat = () => {
    const q = chatInput.trim();
    if (!q || chat.isPending) return;
    // Gate on consent before sending anything to the cloud.
    if (needsConsent) {
      setShowConsent(true);
      return;
    }
    const next = [...chatMsgs, { role: "user" as const, content: q }];
    setChatMsgs(next);
    setChatInput("");
    chat.mutate(next);
  };

  // T11 — consent text + record/revoke. The text query is enabled once the
  // advisor is configured so the modal has content ready when it opens.
  const consentText = useQuery<ConsentText>({
    queryKey: ["advisor-consent-text"],
    queryFn: () => apiFetch<ConsentText>("/api/advisor/consent-text"),
    enabled: configured,
  });

  const consent = useMutation<{ consented: boolean }, Error, boolean>({
    mutationFn: (value) =>
      apiFetch<{ consented: boolean }>("/api/advisor/consent", {
        method: "POST",
        body: JSON.stringify({ consented: value }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["advisor-status"] });
      qc.invalidateQueries({ queryKey: ["advisor-consent-text"] });
    },
  });

  // Analyze is only allowed after consent; otherwise open the gate first.
  const requestAnalyze = () => {
    if (needsConsent) {
      setShowConsent(true);
      return;
    }
    analyze.mutate();
  };
  const acceptConsent = () => consent.mutate(true, { onSuccess: () => setShowConsent(false) });

  // Consent statement in the current language (ar/ur → Arabic, else English).
  const consentBody = i18n.language.startsWith("ar")
    ? consentText.data?.ar
    : consentText.data?.en;

  // Export the AI's analysis as a printable/Save-as-PDF report. Uses a hidden
  // iframe so ONLY the report prints (not the app), and the browser renders
  // Arabic/RTL natively — no backend PDF library or font bundling needed.
  const exportReport = () => {
    const data = analyze.data;
    if (!data) return;
    const isAr = i18n.language.startsWith("ar");
    const now = new Date().toLocaleString(isAr ? "ar-EG" : "en-US");
    const esc = (s: string) =>
      (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const html = `<!doctype html><html dir="${isAr ? "rtl" : "ltr"}" lang="${isAr ? "ar" : "en"}"><head>
<meta charset="utf-8"><title>${esc(t("pages.advisor.reportTitle"))}</title><style>
body{font-family:'Segoe UI',Tahoma,Arial,sans-serif;color:#1a1a1a;line-height:1.7;padding:32px;margin:0}
.brand{color:#4f46e5;font-weight:bold;font-size:12px;letter-spacing:.5px}
h1{font-size:22px;margin:6px 0 2px}.sub{color:#666;font-size:12px;margin:0 0 20px}
.rec{white-space:pre-wrap;font-size:14px}
.meta{margin-top:28px;padding-top:12px;border-top:1px solid #ddd;color:#999;font-size:11px}
@page{margin:16mm}</style></head><body>
<div class="brand">HomeUpdater · محدِّث المنزل</div>
<h1>${esc(t("pages.advisor.reportTitle"))}</h1>
<p class="sub">${esc(t("pages.advisor.reportSub"))} · ${esc(now)}</p>
<div class="rec">${esc(data.recommendations)}</div>
<p class="meta">${esc(t("pages.advisor.poweredBy"))} · Claude ${esc(data.model)}</p>
</body></html>`;
    const iframe = document.createElement("iframe");
    iframe.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";
    document.body.appendChild(iframe);
    const doc = iframe.contentWindow?.document;
    if (!doc) {
      document.body.removeChild(iframe);
      return;
    }
    doc.open();
    doc.write(html);
    doc.close();
    const cleanup = () => setTimeout(() => iframe.remove(), 1500);
    setTimeout(() => {
      iframe.contentWindow?.focus();
      iframe.contentWindow?.print();
      cleanup();
    }, 400);
  };

  const topActions = (analyze.data?.actions ?? []).slice(0, 3);
  const applyTop = () => {
    if (topActions.length === 0) return;
    const list = topActions.map((a, i) => `${i + 1}. ${a.title}`).join("\n");
    if (window.confirm(`${t("pages.advisor.applyConfirm")}\n\n${list}`)) apply.mutate(topActions);
  };

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
          <>
            {needsConsent ? (
              // Consent gate — analysis/chat stay locked until the user accepts.
              <div className="p-3 rounded-lg border border-warning/30 bg-warning/10">
                <p className="text-sm text-fg-muted mb-3">{t("pages.advisor.consentRequired")}</p>
                <button
                  type="button"
                  onClick={() => setShowConsent(true)}
                  className="btn-primary inline-flex items-center gap-2"
                >
                  <ShieldCheck className="w-4 h-4" />
                  {t("pages.advisor.consentReview")}
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={requestAnalyze}
                disabled={analyze.isPending}
                className="btn-primary inline-flex items-center gap-2"
              >
                {analyze.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                {analyze.isPending ? t("pages.advisor.analyzing") : t("pages.advisor.analyze")}
              </button>
            )}
            {consented && (
              <div className="mt-3">
                <button
                  type="button"
                  onClick={() => consent.mutate(false)}
                  disabled={consent.isPending}
                  className="text-xs text-fg-subtle hover:text-danger underline underline-offset-2 transition-colors"
                >
                  {t("pages.advisor.revokeConsent")}
                </button>
              </div>
            )}
          </>
        ) : (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <KeyRound className="w-4 h-4 text-primary" />
              <label htmlFor="advisor-key" className="text-sm font-medium">{t("pages.advisor.keyLabel")}</label>
            </div>
            <p className="text-xs text-fg-muted mb-2">{t("pages.advisor.keyHint")}</p>
            <div className="flex items-center gap-2 flex-wrap">
              <input
                id="advisor-key"
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

      {analyze.isError && !isConsentError(analyze.error) && (
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
          <div className="mt-4 pt-3 border-t border-border flex items-center justify-between gap-2 flex-wrap">
            <span className="text-xs text-fg-subtle inline-flex items-center gap-1">
              <Sparkles className="w-3 h-3" /> {t("pages.advisor.poweredBy")} · {analyze.data.model}
            </span>
            <button
              type="button"
              onClick={exportReport}
              className="btn-secondary text-xs inline-flex items-center gap-2"
            >
              <FileText className="w-4 h-4" /> {t("pages.advisor.exportReport")}
            </button>
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

      {/* Ask-the-advisor chat (read-only Q&A over the same tools) */}
      {configured && (
        <div className="card mt-4">
          <div className="flex items-center gap-2 mb-3">
            <MessageSquare className="w-4 h-4 text-primary" />
            <h3 className="font-bold text-sm">{t("pages.advisor.chatTitle")}</h3>
          </div>
          {chatMsgs.length > 0 && (
            <div className="space-y-2 mb-3 max-h-72 overflow-y-auto">
              {chatMsgs.map((m, i) => (
                <div
                  key={i}
                  className={cn(
                    "text-sm rounded-lg px-3 py-2 whitespace-pre-wrap",
                    m.role === "user" ? "bg-primary/10 ms-8" : "bg-surface-2 me-8",
                  )}
                >
                  {m.content}
                </div>
              ))}
              {chat.isPending && (
                <div className="text-sm text-fg-muted me-8 inline-flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" /> {t("pages.advisor.chatThinking")}
                </div>
              )}
            </div>
          )}
          {chat.isError && !isConsentError(chat.error) && (
            <p className="text-sm text-danger mb-2">
              {t("pages.advisor.failed")} {chat.error.message}
            </p>
          )}
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && sendChat()}
              placeholder={t("pages.advisor.chatPlaceholder")}
              aria-label={t("pages.advisor.chatTitle")}
              className="input flex-1"
            />
            <button
              type="button"
              onClick={sendChat}
              disabled={chat.isPending || !chatInput.trim()}
              className="btn-primary inline-flex items-center gap-2"
              aria-label={t("a11y.send")}
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* T11 — data-sharing consent modal (shown before the first cloud call, or
          when analyze/chat return 403 consent_required). */}
      {showConsent && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
          onClick={() => setShowConsent(false)}
        >
          <div
            className="card max-w-lg w-full max-h-[80vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2 mb-3">
              <ShieldCheck className="w-5 h-5 text-primary" />
              <h3 className="font-bold">{t("pages.advisor.consentTitle")}</h3>
            </div>
            <div className="text-sm text-fg-muted whitespace-pre-wrap leading-relaxed mb-4">
              {consentBody || t("pages.advisor.consentLoading")}
            </div>
            {consent.isError && (
              <p className="mb-3 text-sm text-danger">
                {t("pages.advisor.failed")} {consent.error.message}
              </p>
            )}
            <div className="flex items-center justify-end gap-2 flex-wrap">
              <button
                type="button"
                onClick={() => setShowConsent(false)}
                className="btn-secondary"
              >
                {t("pages.advisor.consentDecline")}
              </button>
              <button
                type="button"
                onClick={acceptConsent}
                disabled={consent.isPending || !consentBody}
                className="btn-primary inline-flex items-center gap-2"
              >
                {consent.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <CheckCircle2 className="w-4 h-4" />
                )}
                {t("pages.advisor.consentAccept")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
