import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  ArrowRight,
  SlidersHorizontal,
  Palette,
  Languages,
  Radar,
  Sparkles,
  Loader2,
  Check,
  KeyRound,
} from "lucide-react";
import { apiFetch, cn, setAuthToken } from "@/lib/utils";
import { useLanguage } from "@/lib/language";
import { useTheme } from "@/lib/theme";

// ================================================================
// صفحة الإعدادات — تجمع المظهر (الثيم) واللغة وإعدادات فحص الشبكة في مكان واحد.
// الثيم واللغة يُطبَّقان فورًا (localStorage). إعدادات الفحص تُحفظ في الخادم عبر
// GET/POST /api/system/settings ثم تُطبَّق حيًّا (وتُعاد جدولة المجدوِل عند تغييره).
// ================================================================

interface ScanSettings {
  scan_method: "auto" | "python" | "nmap";
  scan_scheduler_enabled: boolean;
  scan_interval_minutes: number;
}

export function SettingsPage({
  onBack,
  onOpenAdvisor,
}: {
  onBack: () => void;
  onOpenAdvisor?: () => void;
}) {
  const { t } = useTranslation();
  const { dir, language, setLanguage, languages } = useLanguage();
  const { theme, setTheme, themes } = useTheme();
  const qc = useQueryClient();
  const BackIcon = dir === "rtl" ? ArrowRight : ArrowLeft;

  // --- Scan settings: load from the backend, edit locally, save on demand ---
  const settingsQuery = useQuery<ScanSettings>({
    queryKey: ["system-settings"],
    queryFn: () => apiFetch<ScanSettings>("/api/system/settings"),
  });

  const [form, setForm] = useState<ScanSettings | null>(null);
  // Seed the editable form once the server values arrive (and keep in sync if
  // they change underneath us, e.g. after a save invalidation refetch).
  useEffect(() => {
    if (settingsQuery.data) setForm(settingsQuery.data);
  }, [settingsQuery.data]);

  const save = useMutation<ScanSettings, Error, ScanSettings>({
    mutationFn: (body) =>
      apiFetch<ScanSettings>("/api/system/settings", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: (data) => {
      qc.setQueryData(["system-settings"], data);
      setForm(data);
    },
  });

  const dirty =
    !!form &&
    !!settingsQuery.data &&
    (form.scan_method !== settingsQuery.data.scan_method ||
      form.scan_scheduler_enabled !== settingsQuery.data.scan_scheduler_enabled ||
      form.scan_interval_minutes !== settingsQuery.data.scan_interval_minutes);

  // --- Change the app password (requires the current one). The backend revokes
  // all other sessions and returns a fresh token we must store to stay logged in.
  const [pwCurrent, setPwCurrent] = useState("");
  const [pwNew, setPwNew] = useState("");
  const [pwConfirm, setPwConfirm] = useState("");
  const [pwError, setPwError] = useState("");

  const changePw = useMutation<{ token: string }, Error>({
    mutationFn: () =>
      apiFetch<{ token: string }>("/api/auth/change", {
        method: "POST",
        body: JSON.stringify({ current: pwCurrent, new: pwNew }),
      }),
    onSuccess: (data) => {
      setAuthToken(data.token); // keep this session alive after revoke_all()
      setPwCurrent("");
      setPwNew("");
      setPwConfirm("");
    },
  });

  const canChangePw = pwCurrent.length >= 1 && pwNew.length >= 6 && pwConfirm.length >= 6;
  const submitPw = () => {
    setPwError("");
    if (pwNew.length < 6) return setPwError(t("settings.pwTooShort"));
    if (pwNew !== pwConfirm) return setPwError(t("settings.pwMismatch"));
    changePw.mutate();
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
          <SlidersHorizontal className="w-5 h-5 text-primary" />
          <div>
            <h2 className="text-xl font-display font-bold leading-tight">{t("settings.title")}</h2>
            <p className="text-xs text-fg-muted">{t("settings.subtitle")}</p>
          </div>
        </div>
        <div className="w-20" />
      </div>

      {/* المظهر: الثيم + اللغة */}
      <section className="card mb-5">
        <div className="flex items-center gap-2 mb-4">
          <Palette className="w-4 h-4 text-primary" />
          <h3 className="font-display font-bold">{t("settings.appearance")}</h3>
        </div>

        {/* الثيم */}
        <p className="text-sm font-medium mb-2">{t("settings.themeLabel")}</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-5">
          {themes.map((th) => (
            <button
              key={th.id}
              type="button"
              onClick={() => setTheme(th.id)}
              aria-pressed={theme === th.id}
              className={cn(
                "flex items-center gap-2 rounded-lg border p-2 text-start transition-colors",
                theme === th.id
                  ? "border-primary bg-primary-soft ring-1 ring-primary"
                  : "border-border hover:bg-surface-2",
              )}
            >
              <span className="flex -space-x-1 flex-shrink-0" aria-hidden="true">
                {th.swatches.map((c, i) => (
                  <span
                    key={i}
                    className="w-3.5 h-3.5 rounded-full border border-black/10"
                    style={{ backgroundColor: c }}
                  />
                ))}
              </span>
              <span className="text-sm truncate">{t(th.i18nKey)}</span>
            </button>
          ))}
        </div>

        {/* اللغة */}
        <div className="flex items-center gap-2 mb-2">
          <Languages className="w-4 h-4 text-fg-muted" />
          <p className="text-sm font-medium">{t("settings.languageLabel")}</p>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {languages.map((lng) => (
            <button
              key={lng.code}
              type="button"
              onClick={() => setLanguage(lng.code)}
              aria-pressed={language === lng.code}
              className={cn(
                "flex items-center gap-2 rounded-lg border p-2 text-start transition-colors",
                language === lng.code
                  ? "border-primary bg-primary-soft ring-1 ring-primary"
                  : "border-border hover:bg-surface-2",
              )}
            >
              <span className="text-lg flex-shrink-0" aria-hidden="true">
                {lng.flag}
              </span>
              <span className="text-sm truncate">{lng.nativeName}</span>
            </button>
          ))}
        </div>
      </section>

      {/* فحص الشبكة */}
      <section className="card mb-5">
        <div className="flex items-center gap-2 mb-4">
          <Radar className="w-4 h-4 text-primary" />
          <h3 className="font-display font-bold">{t("settings.scan")}</h3>
        </div>

        {settingsQuery.isLoading && (
          <p className="text-sm text-fg-muted inline-flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" /> {t("status.loading")}
          </p>
        )}
        {settingsQuery.isError && (
          <p className="text-sm text-danger">{t("settings.loadFailed")}</p>
        )}

        {form && (
          <div className="space-y-5">
            {/* طريقة الفحص */}
            <div>
              <label htmlFor="scan-method" className="text-sm font-medium block mb-1">
                {t("settings.scanMethod")}
              </label>
              <select
                id="scan-method"
                className="input w-full"
                value={form.scan_method}
                onChange={(e) =>
                  setForm({ ...form, scan_method: e.target.value as ScanSettings["scan_method"] })
                }
              >
                <option value="auto">{t("settings.scanMethodAuto")}</option>
                <option value="python">{t("settings.scanMethodPython")}</option>
                <option value="nmap">{t("settings.scanMethodNmap")}</option>
              </select>
              <p className="text-xs text-fg-muted mt-1">{t("settings.scanMethodHint")}</p>
            </div>

            {/* الفحص المجدوَل */}
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm font-medium">{t("settings.scheduler")}</p>
                <p className="text-xs text-fg-muted">{t("settings.schedulerHint")}</p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={form.scan_scheduler_enabled}
                aria-label={t("settings.scheduler")}
                onClick={() =>
                  setForm({ ...form, scan_scheduler_enabled: !form.scan_scheduler_enabled })
                }
                className={cn(
                  "relative inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full transition-colors",
                  form.scan_scheduler_enabled ? "bg-primary" : "bg-surface-2 border border-border",
                )}
              >
                <span
                  className={cn(
                    "inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform",
                    form.scan_scheduler_enabled ? "translate-x-6 rtl:-translate-x-6" : "translate-x-1 rtl:-translate-x-1",
                  )}
                />
              </button>
            </div>

            {/* الفاصل الزمني */}
            <div className={cn(!form.scan_scheduler_enabled && "opacity-60")}>
              <label htmlFor="scan-interval" className="text-sm font-medium block mb-1">
                {t("settings.interval")}
              </label>
              <input
                id="scan-interval"
                type="number"
                min={5}
                max={1440}
                className="input w-40"
                value={form.scan_interval_minutes}
                onChange={(e) =>
                  setForm({
                    ...form,
                    scan_interval_minutes: Math.max(5, Math.min(1440, Number(e.target.value) || 5)),
                  })
                }
              />
              <p className="text-xs text-fg-muted mt-1">{t("settings.intervalHint")}</p>
            </div>

            {/* حفظ */}
            <div className="flex items-center gap-3 pt-1">
              <button
                type="button"
                onClick={() => form && save.mutate(form)}
                disabled={!dirty || save.isPending}
                className="btn-primary inline-flex items-center gap-2"
              >
                {save.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Check className="w-4 h-4" />
                )}
                {save.isPending ? t("settings.saving") : t("settings.save")}
              </button>
              {save.isSuccess && !dirty && (
                <span className="text-sm text-success inline-flex items-center gap-1">
                  <Check className="w-4 h-4" /> {t("settings.saved")}
                </span>
              )}
              {save.isError && (
                <span className="text-sm text-danger">
                  {t("settings.saveFailed")} {save.error.message}
                </span>
              )}
            </div>
          </div>
        )}
      </section>

      {/* تغيير كلمة المرور */}
      <section className="card mb-5">
        <div className="flex items-center gap-2 mb-2">
          <KeyRound className="w-4 h-4 text-primary" />
          <h3 className="font-display font-bold">{t("settings.pwSection")}</h3>
        </div>
        <p className="text-sm text-fg-muted mb-4">{t("settings.pwHint")}</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (canChangePw && !changePw.isPending) submitPw();
          }}
          className="space-y-3 max-w-sm"
        >
          <div>
            <label htmlFor="pw-current" className="text-sm font-medium block mb-1">
              {t("settings.pwCurrent")}
            </label>
            <input
              id="pw-current"
              type="password"
              autoComplete="current-password"
              className="input w-full"
              value={pwCurrent}
              onChange={(e) => setPwCurrent(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="pw-new" className="text-sm font-medium block mb-1">
              {t("settings.pwNew")}
            </label>
            <input
              id="pw-new"
              type="password"
              autoComplete="new-password"
              className="input w-full"
              value={pwNew}
              onChange={(e) => setPwNew(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="pw-confirm" className="text-sm font-medium block mb-1">
              {t("settings.pwConfirm")}
            </label>
            <input
              id="pw-confirm"
              type="password"
              autoComplete="new-password"
              className="input w-full"
              value={pwConfirm}
              onChange={(e) => setPwConfirm(e.target.value)}
            />
            <p className="text-xs text-fg-muted mt-1">{t("settings.pwMinHint")}</p>
          </div>

          {(pwError || changePw.isError) && (
            <p className="text-sm text-danger">
              {pwError || `${t("settings.pwFailed")} ${changePw.error?.message ?? ""}`}
            </p>
          )}
          {changePw.isSuccess && !pwError && (
            <p className="text-sm text-success inline-flex items-center gap-1">
              <Check className="w-4 h-4" /> {t("settings.pwSaved")}
            </p>
          )}

          <button
            type="submit"
            disabled={!canChangePw || changePw.isPending}
            className="btn-primary inline-flex items-center gap-2"
          >
            {changePw.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <KeyRound className="w-4 h-4" />
            )}
            {changePw.isPending ? t("settings.pwSaving") : t("settings.pwSave")}
          </button>
        </form>
      </section>

      {/* المستشار الذكي */}
      <section className="card">
        <div className="flex items-center gap-2 mb-2">
          <Sparkles className="w-4 h-4 text-primary" />
          <h3 className="font-display font-bold">{t("settings.aiSection")}</h3>
        </div>
        <p className="text-sm text-fg-muted mb-3">{t("settings.aiHint")}</p>
        {onOpenAdvisor && (
          <button type="button" onClick={onOpenAdvisor} className="btn-secondary inline-flex items-center gap-2">
            <Sparkles className="w-4 h-4" />
            {t("settings.aiOpenAdvisor")}
          </button>
        )}
      </section>
    </div>
  );
}
