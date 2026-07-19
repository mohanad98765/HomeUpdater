import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Languages, Check } from "lucide-react";
import { useLanguage } from "@/lib/language";
import { cn } from "@/lib/utils";

export function LanguageToggle() {
  const { t } = useTranslation();
  const { language, languages, setLanguage } = useLanguage();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const current = languages.find((l) => l.code === language) ?? languages[0];

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={t("language.label")}
        title={t("language.label")}
        className="inline-flex items-center gap-2 px-3 py-2 rounded-md border border-border bg-surface hover:bg-surface-2 transition-colors text-sm text-fg"
      >
        <Languages className="w-4 h-4" />
        <span className="hidden sm:inline">{current.nativeName}</span>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute end-0 mt-2 w-52 rounded-lg border border-border bg-surface shadow-lg z-50 overflow-hidden"
        >
          <div className="px-3 py-2 text-xs font-bold text-fg-muted border-b border-border flex items-center gap-2">
            <Languages className="w-3.5 h-3.5" />
            {t("language.label")}
          </div>
          <ul className="py-1">
            {languages.map((lang) => {
              const active = language === lang.code;
              return (
                <li key={lang.code}>
                  <button
                    type="button"
                    onClick={() => {
                      setLanguage(lang.code);
                      setOpen(false);
                    }}
                    className={cn(
                      "w-full flex items-center gap-3 px-3 py-2 text-sm text-start hover:bg-surface-2 transition-colors",
                      active && "bg-primary-soft text-primary"
                    )}
                    dir={lang.dir}
                  >
                    <span className="text-base flex-shrink-0">{lang.flag}</span>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium truncate">{lang.nativeName}</div>
                      <div className="text-xs text-fg-muted truncate">{lang.englishName}</div>
                    </div>
                    {active && <Check className="w-4 h-4 text-primary flex-shrink-0" />}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
