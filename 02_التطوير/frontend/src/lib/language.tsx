import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import i18n from "../i18n";

// ================================================================
// نظام اللغات
// 6 لغات. الافتراضية: العربية. يَحفظ الاختيار في localStorage.
// يُحدِّث lang و dir على <html> تلقائياً.
// ================================================================

export type LangCode = "ar" | "en" | "fr" | "es" | "tr" | "ur";

export interface LangMeta {
  code: LangCode;
  /** Native name (always shown in its own script) */
  nativeName: string;
  /** English name (for accessibility / fallback) */
  englishName: string;
  /** Direction */
  dir: "rtl" | "ltr";
  /** Flag emoji or icon hint */
  flag: string;
}

export const LANGUAGES: LangMeta[] = [
  { code: "ar", nativeName: "العربية",  englishName: "Arabic",  dir: "rtl", flag: "🇸🇦" },
  { code: "en", nativeName: "English",  englishName: "English", dir: "ltr", flag: "🇺🇸" },
  { code: "fr", nativeName: "Français", englishName: "French",  dir: "ltr", flag: "🇫🇷" },
  { code: "es", nativeName: "Español",  englishName: "Spanish", dir: "ltr", flag: "🇪🇸" },
  { code: "tr", nativeName: "Türkçe",   englishName: "Turkish", dir: "ltr", flag: "🇹🇷" },
  { code: "ur", nativeName: "اردو",     englishName: "Urdu",    dir: "rtl", flag: "🇵🇰" },
];

const STORAGE_KEY = "homeupdater.language";
const DEFAULT_LANG: LangCode = "ar";

// ================================================================
// Context
// ================================================================
interface LanguageContextValue {
  language: LangCode;
  dir: "rtl" | "ltr";
  setLanguage: (code: LangCode) => void;
  languages: LangMeta[];
}

const LanguageContext = createContext<LanguageContextValue | null>(null);

// ================================================================
// Provider
// ================================================================
export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<LangCode>(() => {
    if (typeof window === "undefined") return DEFAULT_LANG;
    const saved = localStorage.getItem(STORAGE_KEY) as LangCode | null;
    if (saved && LANGUAGES.some((l) => l.code === saved)) return saved;
    return DEFAULT_LANG;
  });

  const meta = LANGUAGES.find((l) => l.code === language) ?? LANGUAGES[0];

  // Sync i18next + html attributes
  useEffect(() => {
    i18n.changeLanguage(language);
    document.documentElement.setAttribute("lang", language);
    document.documentElement.setAttribute("dir", meta.dir);
  }, [language, meta.dir]);

  const setLanguage = (code: LangCode) => {
    setLanguageState(code);
    try {
      localStorage.setItem(STORAGE_KEY, code);
    } catch {
      // ignore
    }
  };

  return (
    <LanguageContext.Provider value={{ language, dir: meta.dir, setLanguage, languages: LANGUAGES }}>
      {children}
    </LanguageContext.Provider>
  );
}

// ================================================================
// Hook
// ================================================================
export function useLanguage() {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error("useLanguage must be used inside <LanguageProvider>");
  return ctx;
}
