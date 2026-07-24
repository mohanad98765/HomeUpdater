import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  ArrowRight,
  LifeBuoy,
  Loader2,
  Send,
  KeyRound,
  MessageSquare,
} from "lucide-react";
import { apiFetch, cn } from "@/lib/utils";
import { useLanguage } from "@/lib/language";

// In-app AI help assistant — answers questions about using HomeUpdater. It talks
// to POST /api/advisor/support (no network data, no consent gate) and reuses the
// advisor's Anthropic key. Distinct from the network Advisor.

interface SupportStatus {
  configured: boolean;
}

export function SupportPage({ onBack }: { onBack: () => void }) {
  const { t } = useTranslation();
  const { dir } = useLanguage();
  const BackIcon = dir === "rtl" ? ArrowRight : ArrowLeft;

  const [msgs, setMsgs] = useState<{ role: "user" | "assistant"; content: string }[]>([]);
  const [input, setInput] = useState("");

  const status = useQuery<SupportStatus>({
    queryKey: ["support-status"],
    queryFn: () => apiFetch<SupportStatus>("/api/advisor/support/status"),
  });
  const configured = !!status.data?.configured;

  const ask = useMutation<
    { reply: string },
    Error,
    { role: "user" | "assistant"; content: string }[]
  >({
    mutationFn: (history) =>
      apiFetch<{ reply: string }>("/api/advisor/support", {
        method: "POST",
        body: JSON.stringify({ messages: history }),
      }),
    onSuccess: (data, history) => setMsgs([...history, { role: "assistant", content: data.reply }]),
  });

  const send = () => {
    const q = input.trim();
    if (!q || ask.isPending) return;
    const next = [...msgs, { role: "user" as const, content: q }];
    setMsgs(next);
    setInput("");
    ask.mutate(next);
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
          <LifeBuoy className="w-5 h-5 text-primary" />
          <div>
            <h2 className="text-xl font-display font-bold leading-tight">{t("pages.support.title")}</h2>
            <p className="text-xs text-fg-muted">{t("pages.support.subtitle")}</p>
          </div>
        </div>
        <div className="w-20" />
      </div>

      <div className="card">
        <p className="text-sm text-fg-muted mb-4">{t("pages.support.intro")}</p>

        {!configured && !status.isLoading && (
          <div className="mb-4 p-3 rounded-lg border border-warning/30 bg-warning/10 text-sm flex items-start gap-2">
            <KeyRound className="w-4 h-4 flex-shrink-0 mt-0.5 text-warning" />
            <span className="text-fg-muted">{t("pages.support.needsKey")}</span>
          </div>
        )}

        {msgs.length > 0 && (
          <div className="space-y-2 mb-3 max-h-96 overflow-y-auto">
            {msgs.map((m, i) => (
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
            {ask.isPending && (
              <div className="text-sm text-fg-muted me-8 inline-flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" /> {t("pages.support.thinking")}
              </div>
            )}
          </div>
        )}

        {msgs.length === 0 && (
          <div className="mb-3 flex flex-wrap gap-2">
            {["exHowScan", "exAddWinrm", "exUpdateFail"].map((k) => (
              <button
                key={k}
                type="button"
                disabled={!configured}
                onClick={() => {
                  const q = t(`pages.support.${k}`);
                  const next = [{ role: "user" as const, content: q }];
                  setMsgs(next);
                  ask.mutate(next);
                }}
                className="text-xs px-3 py-1.5 rounded-full border border-border text-fg-muted hover:bg-surface-2 disabled:opacity-50 inline-flex items-center gap-1"
              >
                <MessageSquare className="w-3 h-3" /> {t(`pages.support.${k}`)}
              </button>
            ))}
          </div>
        )}

        {ask.isError && (
          <p className="text-sm text-danger mb-2">
            {t("pages.support.failed")} {ask.error.message}
          </p>
        )}

        <div className="flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder={t("pages.support.placeholder")}
            aria-label={t("pages.support.title")}
            disabled={!configured}
            className="input flex-1"
          />
          <button
            type="button"
            onClick={send}
            disabled={ask.isPending || !input.trim() || !configured}
            className="btn-primary inline-flex items-center gap-2"
            aria-label={t("a11y.send")}
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
