import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Palette, Check, Monitor, Sun, Moon, Waves, Trees, Sunset, Crown, MoonStar } from "lucide-react";
import { useTheme, ThemeId } from "@/lib/theme";
import { cn } from "@/lib/utils";

const ICONS: Record<ThemeId, typeof Sun> = {
  system:   Monitor,
  light:    Sun,
  dark:     Moon,
  ocean:    Waves,
  forest:   Trees,
  sunset:   Sunset,
  royal:    Crown,
  midnight: MoonStar,
};

export function ThemeToggle() {
  const { t } = useTranslation();
  const { theme, themes, setTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on click outside
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const Current = ICONS[theme];

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={t("theme.label")}
        title={t("theme.label")}
        className="inline-flex items-center gap-2 px-3 py-2 rounded-md border border-border bg-surface hover:bg-surface-2 transition-colors text-sm text-fg"
      >
        <Current className="w-4 h-4" />
        <span className="hidden sm:inline">{t(`theme.${theme}` as const)}</span>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute end-0 mt-2 w-56 rounded-lg border border-border bg-surface shadow-lg z-50 overflow-hidden"
        >
          <div className="px-3 py-2 text-xs font-bold text-fg-muted border-b border-border flex items-center gap-2">
            <Palette className="w-3.5 h-3.5" />
            {t("theme.label")}
          </div>
          <ul className="py-1 max-h-80 overflow-auto">
            {themes.map((meta) => {
              const Icon = ICONS[meta.id];
              const active = theme === meta.id;
              return (
                <li key={meta.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setTheme(meta.id);
                      setOpen(false);
                    }}
                    className={cn(
                      "w-full flex items-center gap-3 px-3 py-2 text-sm text-start hover:bg-surface-2 transition-colors",
                      active && "bg-primary-soft text-primary"
                    )}
                  >
                    <Icon className="w-4 h-4 flex-shrink-0" />
                    <span className="flex-1 truncate">{t(meta.i18nKey as never)}</span>
                    {/* Color preview swatches */}
                    <span className="flex gap-0.5 flex-shrink-0">
                      {meta.swatches.map((c, i) => (
                        <span
                          key={i}
                          className="w-2.5 h-2.5 rounded-full border border-black/10"
                          style={{ backgroundColor: c }}
                        />
                      ))}
                    </span>
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
