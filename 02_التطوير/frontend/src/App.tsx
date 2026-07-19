import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  Wifi,
  WifiOff,
  Loader2,
  ShieldCheck,
  ShieldAlert,
  Cpu,
  RefreshCw,
  FlaskConical,
  LayoutDashboard,
  Network,
  Download,
  Trash2,
  Smartphone,
  House,
  Terminal,
} from "lucide-react";
import { apiFetch, cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/ThemeToggle";
import { LanguageToggle } from "@/components/LanguageToggle";
import { DevicesPage } from "@/pages/DevicesPage";
import { UpdatesPage } from "@/pages/UpdatesPage";
import { AndroidPage } from "@/pages/AndroidPage";
import { SecurityPage } from "@/pages/SecurityPage";
import { HomeAssistantPage } from "@/pages/HomeAssistantPage";
import { LinuxPage } from "@/pages/LinuxPage";

// ================================================================
// محدِّث المنزل — App shell + navigation
// ================================================================

interface HealthResponse {
  status: string;
  service: string;
  version: string;
  build_mode?: string;
}
interface VersionResponse {
  app: string;
  version: string;
  build: string;
}

type Page =
  | "dashboard"
  | "devices"
  | "updates"
  | "android"
  | "security"
  | "homeassistant"
  | "linux";

function App() {
  const { t } = useTranslation();
  const [page, setPage] = useState<Page>("dashboard");

  const health = useQuery<HealthResponse>({
    queryKey: ["health"],
    queryFn: () => apiFetch<HealthResponse>("/api/system/health"),
    refetchInterval: 5_000,
  });

  const version = useQuery<VersionResponse>({
    queryKey: ["version"],
    queryFn: () => apiFetch<VersionResponse>("/api/system/version"),
  });

  return (
    <div className="min-h-screen bg-bg text-fg flex flex-col">
      {/* شارة وضع الاختبار */}
      <div className="bg-warning text-white px-4 py-2 text-center text-sm font-bold flex items-center justify-center gap-2 shadow-md">
        <FlaskConical className="w-4 h-4" />
        <span>{t("banner.testMode")}</span>
        <FlaskConical className="w-4 h-4" />
      </div>

      {/* الرأس */}
      <header className="bg-surface border-b border-border shadow-sm sticky top-0 z-30">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between gap-4">
          <button
            type="button"
            onClick={() => setPage("dashboard")}
            className="flex items-center gap-3 hover:opacity-80 transition-opacity min-w-0"
          >
            <div className="w-10 h-10 rounded-lg bg-primary flex items-center justify-center flex-shrink-0">
              <Cpu className="w-6 h-6 text-primary-fg" />
            </div>
            <div className="min-w-0 text-start">
              <h1 className="text-xl font-display font-bold truncate">{t("app.name")}</h1>
              <p className="text-xs text-fg-muted truncate">{t("app.tagline")}</p>
            </div>
          </button>

          {/* Nav tabs */}
          <nav className="hidden md:flex items-center gap-1 bg-surface-2 rounded-lg p-1">
            <NavTab
              active={page === "dashboard"}
              onClick={() => setPage("dashboard")}
              icon={LayoutDashboard}
              label={t("nav.dashboard")}
            />
            <NavTab
              active={page === "devices"}
              onClick={() => setPage("devices")}
              icon={Network}
              label={t("nav.devices")}
            />
            <NavTab
              active={page === "updates"}
              onClick={() => setPage("updates")}
              icon={Download}
              label={t("nav.updates")}
            />
            <NavTab
              active={page === "android"}
              onClick={() => setPage("android")}
              icon={Smartphone}
              label="Android"
            />
            <NavTab
              active={page === "security"}
              onClick={() => setPage("security")}
              icon={ShieldAlert}
              label="الأمان"
            />
            <NavTab
              active={page === "homeassistant"}
              onClick={() => setPage("homeassistant")}
              icon={House}
              label="المنزل الذكي"
            />
            <NavTab
              active={page === "linux"}
              onClick={() => setPage("linux")}
              icon={Terminal}
              label="لينكس"
            />
          </nav>

          <div className="flex items-center gap-2">
            <ConnectionIndicator
              isLoading={health.isLoading}
              isError={health.isError}
              isSuccess={health.isSuccess}
            />
            <LanguageToggle />
            <ThemeToggle />
          </div>
        </div>
      </header>

      {/* المحتوى */}
      <main className="flex-1">
        {page === "dashboard" && (
          <DashboardView
            healthQuery={health}
            versionQuery={version}
            onStartScan={() => setPage("devices")}
          />
        )}
        {page === "devices" && <DevicesPage onBack={() => setPage("dashboard")} />}
        {page === "updates" && <UpdatesPage onBack={() => setPage("dashboard")} />}
        {page === "android" && <AndroidPage onBack={() => setPage("dashboard")} />}
        {page === "security" && <SecurityPage onBack={() => setPage("dashboard")} />}
        {page === "homeassistant" && <HomeAssistantPage onBack={() => setPage("dashboard")} />}
        {page === "linux" && <LinuxPage onBack={() => setPage("dashboard")} />}
      </main>

      {/* التذييل */}
      <footer className="max-w-6xl mx-auto w-full px-6 py-6 text-center text-xs text-fg-subtle">
        {t("info.footer")} · HomeUpdater {version.data?.version} ·
        <span className="text-warning font-bold ms-1">TEST BUILD</span>
      </footer>
    </div>
  );
}

// ================================================================
// Dashboard view
// ================================================================
function DashboardView({
  healthQuery,
  versionQuery,
  onStartScan,
}: {
  healthQuery: ReturnType<typeof useQuery<HealthResponse>>;
  versionQuery: ReturnType<typeof useQuery<VersionResponse>>;
  onStartScan: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const health = healthQuery;
  const version = versionQuery;

  // Quick stat: how many devices are stored
  const stats = useQuery<{ total: number; online: number }>({
    queryKey: ["device-stats"],
    queryFn: () => apiFetch<{ total: number; online: number }>("/api/devices/stats"),
    staleTime: 30_000,
  });

  // Clear all stored devices, then jump to the Devices page so the user can rescan
  const clearDevices = useMutation<{ deleted: number }>({
    mutationFn: () => apiFetch<{ deleted: number }>("/api/devices", { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      qc.invalidateQueries({ queryKey: ["device-stats"] });
      onStartScan();
    },
  });

  const onClearClick = () => {
    const count = stats.data?.total ?? 0;
    if (window.confirm(t("dashboard.clearConfirm", { count }))) {
      clearDevices.mutate();
    }
  };

  return (
    <div className="max-w-6xl mx-auto px-6 py-12">
      <div className="card text-center max-w-2xl mx-auto">
        <div className="w-16 h-16 rounded-full bg-primary-soft flex items-center justify-center mx-auto mb-4">
          <ShieldCheck className="w-8 h-8 text-primary" />
        </div>

        <h2 className="text-3xl font-display font-bold mb-2">{t("welcome.title")}</h2>
        <p className="text-fg-muted mb-8">{t("welcome.subtitle")}</p>

        {/* معلومات النظام */}
        <div className="bg-surface-2 rounded-lg p-4 text-start mb-6">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <InfoRow
              label={t("info.backendStatus")}
              value={
                health.isLoading
                  ? t("status.loading")
                  : health.isError
                    ? t("status.disconnected")
                    : t("status.connected")
              }
              tone={health.isError ? "danger" : health.isSuccess ? "success" : "info"}
            />
            <InfoRow label={t("info.version")} value={version.data?.version || "—"} tone="info" />
            <InfoRow label={t("info.service")} value={health.data?.service || "—"} tone="info" />
            <InfoRow label={t("info.build")} value={version.data?.build || "—"} tone="info" />
          </div>
        </div>

        <div className="flex items-center justify-center gap-3 flex-wrap">
          <button
            type="button"
            onClick={onStartScan}
            disabled={!health.isSuccess}
            className="btn-primary inline-flex items-center gap-2"
          >
            <RefreshCw className="w-4 h-4" />
            {t("welcome.scan")}
          </button>

          {(stats.data?.total ?? 0) > 0 && (
            <button
              type="button"
              onClick={onClearClick}
              disabled={clearDevices.isPending || !health.isSuccess}
              className="btn-secondary inline-flex items-center gap-2 text-danger"
              title={t("dashboard.clearDevices")}
            >
              {clearDevices.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Trash2 className="w-4 h-4" />
              )}
              {t("dashboard.clearDevices")}
              <span className="text-xs opacity-70">({stats.data?.total})</span>
            </button>
          )}
        </div>

        {clearDevices.data && (
          <p className="mt-4 text-sm text-success">
            {t("dashboard.cleared", { count: clearDevices.data.deleted })}
          </p>
        )}

        {health.isError && (
          <div className="mt-6 p-4 bg-danger/10 border border-danger/30 rounded-md text-start text-sm text-danger">
            <p className="font-bold mb-1">⚠️ {t("info.backendError")}</p>
            <p>{t("info.backendErrorHelp")}</p>
          </div>
        )}
      </div>

      {/* المرحلة الحالية */}
      <div className="mt-8 max-w-2xl mx-auto text-center">
        <p className="text-xs text-fg-subtle">
          🏗️ {t("info.currentPhase")}: <span className="font-mono">{t("info.phaseDescription")}</span>
        </p>
      </div>
    </div>
  );
}

// ================================================================
// Reusable bits
// ================================================================
function NavTab({
  active,
  onClick,
  icon: Icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: typeof Cpu;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "px-3 py-1.5 rounded-md text-sm font-medium transition-colors inline-flex items-center gap-2",
        active
          ? "bg-surface text-primary shadow-sm"
          : "text-fg-muted hover:text-fg hover:bg-surface/60"
      )}
    >
      <Icon className="w-4 h-4" />
      {label}
    </button>
  );
}

function ConnectionIndicator({
  isLoading,
  isError,
  isSuccess,
}: {
  isLoading: boolean;
  isError: boolean;
  isSuccess: boolean;
}) {
  const { t } = useTranslation();
  if (isLoading) {
    return (
      <div className="hidden md:flex items-center gap-2 text-fg-muted text-sm px-3 py-2">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span>{t("status.checking")}</span>
      </div>
    );
  }
  if (isError) {
    return (
      <div className="hidden md:flex items-center gap-2 text-danger text-sm px-3 py-2">
        <WifiOff className="w-4 h-4" />
        <span>{t("status.disconnected")}</span>
      </div>
    );
  }
  if (isSuccess) {
    return (
      <div className="hidden md:flex items-center gap-2 text-success text-sm px-3 py-2">
        <Wifi className="w-4 h-4" />
        <span>{t("status.connected")}</span>
      </div>
    );
  }
  return null;
}

function InfoRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "success" | "danger" | "info";
}) {
  const toneClass =
    tone === "success" ? "text-success" : tone === "danger" ? "text-danger" : "text-fg";
  return (
    <div className="flex items-center justify-between border-b border-border last:border-0 py-1.5">
      <span className="text-fg-muted">{label}</span>
      <span className={`font-mono font-medium ${toneClass}`}>{value}</span>
    </div>
  );
}

export default App;
