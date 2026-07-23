import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { KeyRound, Radar, ListChecks, Sparkles, X, ArrowLeft, ArrowRight, Check } from "lucide-react";
import { useLanguage } from "@/lib/language";
import { cn } from "@/lib/utils";

// The four first-run steps. Icons mirror the app's own iconography:
// KeyRound = app password, Radar = network scan, ListChecks = review devices,
// Sparkles = AI Advisor (same icon used in the nav + AdvisorPage).
const STEPS = [
  { icon: KeyRound, titleKey: "onboarding.step1Title", bodyKey: "onboarding.step1Body" },
  { icon: Radar, titleKey: "onboarding.step2Title", bodyKey: "onboarding.step2Body" },
  { icon: ListChecks, titleKey: "onboarding.step3Title", bodyKey: "onboarding.step3Body" },
  { icon: Sparkles, titleKey: "onboarding.step4Title", bodyKey: "onboarding.step4Body" },
] as const;

/**
 * First-run guided tour. Purely presentational: the parent (App) owns the
 * "seen" flag and decides when to render this. `onDismiss` fires on skip / X /
 * Esc / backdrop (mark seen, close). `onFinish` fires on the final button
 * (mark seen, close, and jump the user into the first task — a network scan).
 */
export function OnboardingTour({
  onDismiss,
  onFinish,
}: {
  onDismiss: () => void;
  onFinish: () => void;
}) {
  const { t } = useTranslation();
  const { dir } = useLanguage();
  const [step, setStep] = useState(0);
  const dialogRef = useRef<HTMLDivElement>(null);
  const primaryRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  const total = STEPS.length;
  const isLast = step === total - 1;
  const current = STEPS[step];
  const Icon = current.icon;
  // Forward/back arrows follow reading direction so "next" always points ahead.
  const NextIcon = dir === "rtl" ? ArrowLeft : ArrowRight;
  const BackIcon = dir === "rtl" ? ArrowRight : ArrowLeft;

  // Capture whatever opened the tour (e.g. the header Help button), move focus
  // into the dialog, and restore it to the opener on close — expected modal
  // focus behaviour for keyboard users.
  useEffect(() => {
    openerRef.current = (document.activeElement as HTMLElement) ?? null;
    primaryRef.current?.focus();
    return () => openerRef.current?.focus?.();
  }, []);

  // Esc dismisses, mirroring the advisor consent modal.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onDismiss();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDismiss]);

  const next = () => (isLast ? onFinish() : setStep((s) => Math.min(s + 1, total - 1)));
  const back = () => setStep((s) => Math.max(s - 1, 0));

  // Focus trap: keep Tab / Shift+Tab within the dialog to honour aria-modal.
  const onDialogKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== "Tab") return;
    const nodes = dialogRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input, [tabindex]:not([tabindex="-1"])',
    );
    if (!nodes || nodes.length === 0) return;
    const list = Array.from(nodes);
    const first = list[0];
    const last = list[list.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && active === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/50"
      onClick={onDismiss}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-title"
        className="card w-full max-w-md focus:outline-none"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onDialogKeyDown}
      >
        {/* header: tour label + close */}
        <div className="flex items-center justify-between mb-4">
          <span className="text-xs font-bold uppercase tracking-wide text-primary">
            {t("onboarding.tourTitle")}
          </span>
          <button
            type="button"
            onClick={onDismiss}
            className="rounded-md p-1 text-fg-subtle hover:text-fg hover:bg-surface-2 transition-colors"
            aria-label={t("onboarding.close")}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* step icon + text — announced on change so screen readers hear the
            new step content, not just the position counter below. */}
        <div className="text-center" aria-live="polite" aria-atomic="true">
          <div className="w-16 h-16 rounded-2xl bg-primary/15 text-primary flex items-center justify-center mx-auto mb-4">
            <Icon className="w-8 h-8" />
          </div>
          <h2 id="onboarding-title" className="text-xl font-display font-bold mb-2">
            {t(current.titleKey)}
          </h2>
          <p className="text-sm text-fg-muted leading-relaxed min-h-[3rem]">{t(current.bodyKey)}</p>
        </div>

        {/* progress dots */}
        <div className="flex items-center justify-center gap-2 my-5" aria-hidden="true">
          {STEPS.map((_, idx) => (
            <span
              key={idx}
              className={cn(
                "h-2 rounded-full transition-all",
                idx === step ? "w-6 bg-primary" : "w-2 bg-border",
              )}
            />
          ))}
        </div>
        <p className="sr-only" aria-live="polite">
          {t("onboarding.stepOf", { current: step + 1, total })}
        </p>

        {/* controls */}
        <div className="flex items-center justify-between gap-2">
          {step > 0 ? (
            <button
              type="button"
              onClick={back}
              className="btn-secondary inline-flex items-center gap-2"
            >
              <BackIcon className="w-4 h-4" />
              {t("onboarding.back")}
            </button>
          ) : (
            <button
              type="button"
              onClick={onDismiss}
              className="text-sm text-fg-subtle hover:text-fg underline underline-offset-2 transition-colors"
            >
              {t("onboarding.skip")}
            </button>
          )}

          <button
            ref={primaryRef}
            type="button"
            onClick={next}
            className="btn-primary inline-flex items-center gap-2"
          >
            {isLast ? (
              <>
                <Check className="w-4 h-4" />
                {t("onboarding.finish")}
              </>
            ) : (
              <>
                {t("onboarding.next")}
                <NextIcon className="w-4 h-4" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
