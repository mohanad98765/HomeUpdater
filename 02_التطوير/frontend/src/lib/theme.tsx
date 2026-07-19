import { createContext, useContext, useEffect, useState, ReactNode } from "react";

// ================================================================
// نظام الثيمات
// 7 ثيمات + System (auto). الحفظ في localStorage.
// ================================================================

export type ThemeId =
  | "system"
  | "light"
  | "dark"
  | "ocean"
  | "forest"
  | "sunset"
  | "royal"
  | "midnight";

export interface ThemeMeta {
  id: ThemeId;
  /** key used by i18n to look up the translated name */
  i18nKey: string;
  /** Resolved theme when this is "system" — empty string for non-system */
  isDark: boolean;
  /** Preview swatches used by the picker */
  swatches: [string, string, string];
}

export const THEMES: ThemeMeta[] = [
  { id: "system",   i18nKey: "theme.system",   isDark: false, swatches: ["#0D47A1", "#1E293B", "#26A69A"] },
  { id: "light",    i18nKey: "theme.light",    isDark: false, swatches: ["#0D47A1", "#FFFFFF", "#26A69A"] },
  { id: "dark",     i18nKey: "theme.dark",     isDark: true,  swatches: ["#1E293B", "#60A5FA", "#4DD0E0"] },
  { id: "ocean",    i18nKey: "theme.ocean",    isDark: false, swatches: ["#0E7490", "#E0F2FE", "#14B8A6"] },
  { id: "forest",   i18nKey: "theme.forest",   isDark: false, swatches: ["#166534", "#F7FEE7", "#84CC16"] },
  { id: "sunset",   i18nKey: "theme.sunset",   isDark: false, swatches: ["#9A3412", "#FFFBEB", "#EA580C"] },
  { id: "royal",    i18nKey: "theme.royal",    isDark: true,  swatches: ["#1E1B4B", "#C084FC", "#D946EF"] },
  { id: "midnight", i18nKey: "theme.midnight", isDark: true,  swatches: ["#030712", "#60A5FA", "#2DD4BF"] },
];

const STORAGE_KEY = "homeupdater.theme";
const DEFAULT_THEME: ThemeId = "system";

// ================================================================
// Context
// ================================================================
interface ThemeContextValue {
  theme: ThemeId;
  resolvedTheme: Exclude<ThemeId, "system">;
  setTheme: (id: ThemeId) => void;
  themes: ThemeMeta[];
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

// ================================================================
// Provider
// ================================================================
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeId>(() => {
    if (typeof window === "undefined") return DEFAULT_THEME;
    const saved = localStorage.getItem(STORAGE_KEY) as ThemeId | null;
    return saved && THEMES.some((t) => t.id === saved) ? saved : DEFAULT_THEME;
  });

  const [systemPrefersDark, setSystemPrefersDark] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });

  // Listen for OS preference changes (only relevant when theme === "system")
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => setSystemPrefersDark(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const resolvedTheme: Exclude<ThemeId, "system"> =
    theme === "system" ? (systemPrefersDark ? "dark" : "light") : theme;

  // Apply data-theme to <html>
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", resolvedTheme);
  }, [resolvedTheme]);

  const setTheme = (id: ThemeId) => {
    setThemeState(id);
    try {
      localStorage.setItem(STORAGE_KEY, id);
    } catch {
      // localStorage may be disabled — fail silently
    }
  };

  return (
    <ThemeContext.Provider value={{ theme, resolvedTheme, setTheme, themes: THEMES }}>
      {children}
    </ThemeContext.Provider>
  );
}

// ================================================================
// Hook
// ================================================================
export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
  return ctx;
}
