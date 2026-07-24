import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Wand2, Cpu, Cloud, X, Loader2, ShieldCheck, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { solveProblem } from "@/lib/ai/router";
import { localSupported } from "@/lib/ai/localEngine";
import type { ProviderId } from "@/lib/ai/provider";

// زرّ «حل المشكلة» + نافذة اختيار المزوّد (محليّ مجانيّ / سحابيّ مدفوع). مكوّن
// مستقلّ تمامًا — يستقبل السياق فقط، ويتولّى الموجِّه (router) بقيّة المنطق.
export function SolveProblemButton({ context }: { context: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<ProviderId | null>(null);
  const [answer, setAnswer] = useState("");
  const [pct, setPct] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [tone, setTone] = useState<"info" | "warn" | "err">("info");

  const gpu = localSupported(); // WebGPU حاضر؟ (يحدّد وصف الخيار المحليّ)

  const run = async (choice: ProviderId) => {
    setBusy(choice);
    setAnswer("");
    setNote("");
    setPct(null);
    try {
      const res = await solveProblem(choice, {
        question: "اشرح خطورة هذه الثغرات وكيف أعالجها خطوة بخطوة.",
        context,
        onToken: (d) => setAnswer((a) => a + d), // بثّ فوريّ
        onProgress: (f) => setPct(Math.round(f * 100)), // تقدّم تنزيل النموذج المحليّ
      });
      setPct(null);
      if (res.fellBack) {
        setNote(t("pages.sec.solve.fellBack"));
        setTone("warn");
      } else {
        setNote(res.providerUsed === "local" ? t("pages.sec.solve.usedLocal") : t("pages.sec.solve.usedCloud"));
        setTone("info");
      }
    } catch (e) {
      setNote((e as Error).message); // رسالة خطأ واضحة (بلا انهيار صامت)
      setTone("err");
      setPct(null);
    } finally {
      setBusy(null);
    }
  };

  const close = () => {
    if (!busy) {
      setOpen(false);
      setAnswer("");
      setNote("");
    }
  };

  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className="btn-primary inline-flex items-center gap-2">
        <Wand2 className="w-4 h-4" />
        {t("pages.sec.solve.button")}
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={close}>
          <div
            className="card max-w-lg w-full max-h-[85vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Wand2 className="w-5 h-5 text-primary" />
                <h3 className="font-bold">{t("pages.sec.solve.title")}</h3>
              </div>
              <button type="button" onClick={close} aria-label={t("banner.dismiss")} className="p-1 rounded hover:bg-surface-2">
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* الخياران — يظهران قبل أي إجابة */}
            {!answer && !busy && (
              <>
                <p className="text-sm text-fg-muted mb-3">{t("pages.sec.solve.intro")}</p>
                <div className="grid gap-2">
                  <button
                    type="button"
                    onClick={() => run("local")}
                    className="text-start p-3 rounded-lg border border-border hover:border-primary hover:bg-surface-2 transition-colors"
                  >
                    <div className="flex items-center gap-2 font-medium">
                      <Cpu className="w-4 h-4 text-primary" /> {t("pages.sec.solve.useLocal")}
                    </div>
                    <div className="text-xs text-fg-muted mt-1">
                      {gpu ? t("pages.sec.solve.localHint") : t("pages.sec.solve.localUnsupported")}
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => run("cloud")}
                    className="text-start p-3 rounded-lg border border-border hover:border-primary hover:bg-surface-2 transition-colors"
                  >
                    <div className="flex items-center gap-2 font-medium">
                      <Cloud className="w-4 h-4 text-primary" /> {t("pages.sec.solve.useCloud")}
                    </div>
                    <div className="text-xs text-fg-muted mt-1">{t("pages.sec.solve.cloudHint")}</div>
                  </button>
                </div>
              </>
            )}

            {busy && (
              <div className="text-sm text-fg-muted inline-flex items-center gap-2 mb-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                {pct !== null ? t("pages.sec.solve.downloading", { pct }) : t("pages.sec.solve.thinking")}
              </div>
            )}

            {answer && (
              <div className="text-sm whitespace-pre-wrap leading-relaxed bg-surface-2 rounded-lg p-3 mt-2">
                {answer}
              </div>
            )}

            {note && (
              <p
                className={cn(
                  "text-xs mt-3 inline-flex items-center gap-1",
                  tone === "err" ? "text-danger" : tone === "warn" ? "text-warning" : "text-success",
                )}
              >
                {tone === "err" ? <AlertTriangle className="w-3 h-3" /> : <ShieldCheck className="w-3 h-3" />}
                {note}
              </p>
            )}
          </div>
        </div>
      )}
    </>
  );
}
