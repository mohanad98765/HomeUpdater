import { useState, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  ArrowRight,
  RefreshCw,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  Download,
  Activity,
  ShieldCheck,
  Package,
  HardDrive,
  RotateCw,
  Monitor,
  Power,
  Info,
} from "lucide-react";
import { apiFetch, cn } from "@/lib/utils";
import { useLanguage } from "@/lib/language";

// ================================================================
// Phase 1.4 — Windows Updates page
// ================================================================

interface UpdateRow {
  id: number;
  update_id: string;
  title: string;
  description: string;
  kb_articles: string[];
  categories: string[];
  severity: string;
  size_mb: number;
  is_downloaded: boolean;
  requires_reboot: boolean;
  is_installed: boolean;
  install_result: number;
  release_date: string;
  last_checked: string | null;
}

interface UpdatesList {
  pending: UpdateRow[];
  installed_recent: UpdateRow[];
  total_pending: number;
  total_size_mb: number;
  last_checked: string | null;
}

type Phase =
  | "idle"
  | "checking"
  | "downloading"
  | "installing"
  | "rebooting"
  | "done"
  | "error";

interface ProgressEvent {
  elapsed_seconds: number;
  phase: Phase;
  message: string;
}
interface ProgressState {
  is_running: boolean;
  operation: string;
  phase: Phase;
  total: number;
  completed: number;
  elapsed_seconds: number;
  last_message: string;
  error: string | null;
  log: ProgressEvent[];
}

interface InstallResponse {
  installed: number;
  total: number;
  reboot_required: boolean;
  results: Array<{
    update_id: string;
    title: string;
    result_code: number;
    succeeded: boolean;
  }>;
}

interface SystemInfo {
  version: string;
  build_mode: string;
  hostname: string;
  user: string;
  python_version: string;
  platform: string;
  system: string;
  release: string;
  machine: string;
}

// ================================================================
// Page wrapper with tabs (Windows / Software / Drivers)
// ================================================================
import { SoftwareUpdatesView } from "./SoftwareUpdatesView";

type Tab = "windows" | "software" | "drivers";

export function UpdatesPage({ onBack }: { onBack: () => void }) {
  const { t } = useTranslation();
  const { dir } = useLanguage();
  const [tab, setTab] = useState<Tab>("windows");

  const BackIcon = dir === "rtl" ? ArrowRight : ArrowLeft;

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      {/* Top bar with back + tab strip */}
      <div className="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <button
          type="button"
          onClick={onBack}
          className="btn-secondary inline-flex items-center gap-2"
        >
          <BackIcon className="w-4 h-4" />
          <span className="hidden sm:inline">{t("nav.dashboard")}</span>
        </button>

        <div className="inline-flex bg-surface-2 rounded-lg p-1 gap-1">
          <TabButton active={tab === "windows"} onClick={() => setTab("windows")}>
            {t("updateTabs.windows")}
          </TabButton>
          <TabButton active={tab === "software"} onClick={() => setTab("software")}>
            {t("updateTabs.software")}
          </TabButton>
          <TabButton active={tab === "drivers"} onClick={() => setTab("drivers")}>
            {t("updateTabs.drivers")}
          </TabButton>
        </div>
      </div>

      {tab === "windows" && <WUAUpdatesView kind="windows" />}
      {tab === "software" && <SoftwareUpdatesView />}
      {tab === "drivers" && <WUAUpdatesView kind="drivers" />}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
        active
          ? "bg-surface text-primary shadow-sm"
          : "text-fg-muted hover:text-fg hover:bg-surface/60"
      )}
    >
      {children}
    </button>
  );
}

// ================================================================
// Generic WUA view — works for both Windows updates and Drivers
// ================================================================
function WUAUpdatesView({ kind }: { kind: "windows" | "drivers" }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Endpoints differ only by /windows vs /drivers
  const endpoint = `/api/updates/${kind}`;

  const sysInfo = useQuery<SystemInfo>({
    queryKey: ["system-info"],
    queryFn: () => apiFetch<SystemInfo>("/api/system/info"),
    staleTime: 60_000,
  });

  const list = useQuery<UpdatesList>({
    queryKey: ["wua-updates", kind],
    queryFn: () => apiFetch<UpdatesList>(endpoint),
  });

  const check = useMutation({
    mutationFn: () =>
      apiFetch(`${endpoint}/check`, { method: "POST", body: JSON.stringify({}) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wua-updates", kind] });
      setSelectedIds(new Set());
    },
  });

  const install = useMutation<InstallResponse>({
    mutationFn: () =>
      apiFetch<InstallResponse>(`${endpoint}/install`, {
        method: "POST",
        body: JSON.stringify({ update_ids: Array.from(selectedIds) }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wua-updates", kind] });
      setSelectedIds(new Set());
    },
  });

  // Live progress polling while a check or install is running
  const progress = useQuery<ProgressState>({
    queryKey: ["update-status"],
    queryFn: () => apiFetch<ProgressState>("/api/updates/windows/status"),
    enabled: check.isPending || install.isPending,
    refetchInterval: 1000,
  });

  // Reboot mutation (Windows shutdown /r /t 60)
  const reboot = useMutation<{ status: string; delay_seconds?: number }>({
    mutationFn: () =>
      apiFetch("/api/system/reboot", {
        method: "POST",
        body: JSON.stringify({ delay_seconds: 60 }),
      }),
  });

  const pending = list.data?.pending ?? [];
  const totalSize = useMemo(() => {
    if (selectedIds.size === 0) return list.data?.total_size_mb ?? 0;
    return pending
      .filter((u) => selectedIds.has(u.update_id))
      .reduce((acc, u) => acc + u.size_mb, 0);
  }, [pending, selectedIds, list.data?.total_size_mb]);

  const allSelected = pending.length > 0 && pending.every((u) => selectedIds.has(u.update_id));
  const toggleAll = () => {
    if (allSelected) setSelectedIds(new Set());
    else setSelectedIds(new Set(pending.map((u) => u.update_id)));
  };
  const toggleOne = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const onInstallClick = () => {
    const count = selectedIds.size || pending.length;
    if (count === 0) return;
    if (window.confirm(t("updates.confirmInstall", { count }))) {
      install.mutate();
    }
  };

  const lastChecked = list.data?.last_checked
    ? new Date(list.data.last_checked).toLocaleString(i18n.language)
    : t("updates.neverChecked");

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <div>
          <h2 className="text-xl font-display font-bold">{t("updates.title")}</h2>
          <p className="text-xs text-fg-muted">
            {t("updates.lastChecked")}: {lastChecked}
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={() => check.mutate()}
            disabled={check.isPending || install.isPending}
            className="btn-secondary inline-flex items-center gap-2"
          >
            {check.isPending ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {t("updates.checking")}
              </>
            ) : (
              <>
                <RefreshCw className="w-4 h-4" />
                {t("updates.check")}
              </>
            )}
          </button>

          {pending.length > 0 && (
            <button
              type="button"
              onClick={onInstallClick}
              disabled={install.isPending || check.isPending}
              className="btn-primary inline-flex items-center gap-2"
            >
              {install.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {t("updates.installing")}
                </>
              ) : (
                <>
                  <Download className="w-4 h-4" />
                  {selectedIds.size > 0 ? t("updates.install") : t("updates.installAll")}
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* "This PC" identity card */}
      {sysInfo.data && (
        <div className="card mb-6 flex items-center gap-4 flex-wrap">
          <div className="w-12 h-12 rounded-xl bg-primary/10 text-primary flex items-center justify-center flex-shrink-0">
            <Monitor className="w-6 h-6" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-xs text-fg-muted mb-1">{t("thisPc.label")}</div>
            <div className="font-bold truncate" dir="ltr">
              {sysInfo.data.hostname || "—"}
              {sysInfo.data.user && (
                <span className="text-fg-muted font-normal"> · {sysInfo.data.user}</span>
              )}
            </div>
            <div className="text-xs text-fg-muted truncate" dir="ltr">
              {sysInfo.data.system} {sysInfo.data.release} · {sysInfo.data.machine}
            </div>
          </div>
        </div>
      )}

      {/* Scope note — what this tab updates, and where other devices are handled */}
      <div className="card mb-6 flex items-start gap-3 text-sm border-info/30 bg-info/5">
        <Info className="w-5 h-5 text-info flex-shrink-0 mt-0.5" />
        <div className="text-fg-muted">
          تحديثات <span className="font-semibold text-fg">Windows والبرامج والتعريفات</span> هنا تُطبَّق
          على <span className="font-semibold text-fg">هذا الجهاز</span> (المركز الذي يعمل عليه HomeUpdater)،
          لأن أدوات التحديث (<span dir="ltr">Windows Update</span> و<span dir="ltr">winget</span>) تنفَّذ محلياً.
          لتحديث أجهزة أخرى من نفس المكان استخدم تبويباتها:{" "}
          <span className="font-semibold text-fg">Android</span> (لاسلكياً عبر ADB)،{" "}
          <span className="font-semibold text-fg">لينكس/SSH</span>، و<span className="font-semibold text-fg">المنزل الذكي</span>{" "}
          (Home Assistant). تحديث أجهزة <span dir="ltr">Windows</span> أخرى <span className="font-semibold text-fg">عن بُعد</span>{" "}
          يتطلّب تفعيل <span dir="ltr">WinRM</span> على كل جهاز — ميزة مخطَّطة (المرحلة 1.6).
        </div>
      </div>

      {/* Stat row */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
        <StatTile
          icon={Package}
          label={t("updates.pending", { count: pending.length })}
          value={pending.length.toString()}
          accent={pending.length > 0 ? "warning" : "success"}
        />
        <StatTile
          icon={HardDrive}
          label={t("updates.totalSize", { mb: totalSize.toFixed(1) })}
          value={`${totalSize.toFixed(1)} MB`}
          accent="info"
        />
        <StatTile
          icon={RotateCw}
          label={t("updates.rebootRequired")}
          value={pending.filter((u) => u.requires_reboot).length.toString()}
          accent="primary"
        />
      </div>

      {/* Live activity log during operations */}
      {(check.isPending || install.isPending || progress.data?.is_running) && (
        <ActivityLog progress={progress.data} />
      )}

      {/* Install result summary */}
      {install.data && !install.isPending && (
        <div
          className={cn(
            "mb-6 p-4 rounded-lg border flex items-start gap-3 text-sm flex-wrap",
            install.data.installed === install.data.total
              ? "border-success/30 bg-success/10 text-success"
              : "border-warning/30 bg-warning/10 text-warning"
          )}
        >
          <CheckCircle2 className="w-5 h-5 flex-shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="font-bold">
              {t("updates.installSuccess", {
                installed: install.data.installed,
                total: install.data.total,
              })}
            </p>
            {install.data.reboot_required && (
              <p className="mt-1 font-bold">{t("updates.rebootMsg")}</p>
            )}
          </div>

          {install.data.reboot_required && !reboot.data && (
            <button
              type="button"
              onClick={() => {
                if (window.confirm(t("reboot.confirm"))) {
                  reboot.mutate();
                }
              }}
              disabled={reboot.isPending}
              className="btn-primary inline-flex items-center gap-2 flex-shrink-0"
            >
              {reboot.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Power className="w-4 h-4" />
              )}
              {t("reboot.button")}
            </button>
          )}
        </div>
      )}

      {/* Reboot scheduled banner */}
      {reboot.data?.status === "scheduled" && (
        <div className="mb-6 p-4 rounded-lg border border-warning/40 bg-warning/15 text-warning flex items-start gap-3 flex-wrap">
          <Power className="w-5 h-5 flex-shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="font-bold">
              {t("reboot.scheduled", { seconds: reboot.data.delay_seconds ?? 60 })}
            </p>
          </div>
          <button
            type="button"
            onClick={() =>
              apiFetch("/api/system/reboot", {
                method: "POST",
                body: JSON.stringify({ cancel: true }),
              }).then(() => reboot.reset())
            }
            className="btn-secondary text-sm"
          >
            {t("reboot.cancel")}
          </button>
        </div>
      )}

      {/* Errors */}
      {(check.isError || install.isError) && (
        <div className="mb-6 p-4 rounded-lg border border-danger/30 bg-danger/10 text-danger flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-bold mb-1">
              {t(check.isError ? "updates.checkFailed" : "updates.installFailed")}
            </p>
            <p className="text-sm font-mono">
              {(check.error || install.error) instanceof Error
                ? (check.error || install.error)!.message
                : ""}
            </p>
          </div>
        </div>
      )}

      {/* List or empty state */}
      {list.isLoading ? (
        <div className="card text-center py-12">
          <Loader2 className="w-8 h-8 animate-spin mx-auto mb-3 text-fg-muted" />
          <p className="text-fg-muted">{t("status.loading")}</p>
        </div>
      ) : pending.length === 0 ? (
        <EmptyState
          everChecked={!!list.data?.last_checked}
          onCheck={() => check.mutate()}
          isChecking={check.isPending}
        />
      ) : (
        <UpdatesTable
          updates={pending}
          selectedIds={selectedIds}
          allSelected={allSelected}
          onToggleAll={toggleAll}
          onToggleOne={toggleOne}
          disabled={install.isPending}
        />
      )}
    </div>
  );
}

// ================================================================
// Subcomponents
// ================================================================
function StatTile({
  icon: Icon,
  label,
  value,
  accent,
}: {
  icon: typeof Package;
  label: string;
  value: string;
  accent: "primary" | "success" | "warning" | "info";
}) {
  const colors: Record<string, string> = {
    primary: "bg-primary/10 text-primary",
    success: "bg-success/10 text-success",
    warning: "bg-warning/10 text-warning",
    info: "bg-info/10 text-info",
  };
  return (
    <div className="card !p-4 flex items-center gap-3">
      <div
        className={cn("w-10 h-10 rounded-lg flex items-center justify-center", colors[accent])}
      >
        <Icon className="w-5 h-5" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-xs text-fg-muted truncate">{label}</div>
        <div className="text-xl font-display font-bold tabular-nums">{value}</div>
      </div>
    </div>
  );
}

function ActivityLog({ progress }: { progress: ProgressState | undefined }) {
  const { t } = useTranslation();
  if (!progress) return null;

  const elapsed = progress.elapsed_seconds;
  const log = progress.log ?? [];
  const pct =
    progress.total > 0 ? Math.min(100, (progress.completed / progress.total) * 100) : 0;

  return (
    <div className="card mb-6 border-primary/30 bg-primary-soft/30">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-primary animate-pulse" />
          <h3 className="font-bold">
            {t(`updates.progress.${progress.phase}` as never, { defaultValue: progress.phase })}
          </h3>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="font-mono text-primary font-bold">
            {elapsed.toFixed(1)}s
          </span>
          {progress.total > 0 && (
            <span className="badge badge-info">
              {progress.completed}/{progress.total}
            </span>
          )}
        </div>
      </div>

      {/* Progress bar */}
      {progress.total > 0 && (
        <div className="h-2 bg-bg/60 rounded-full overflow-hidden mb-3">
          <div
            className="h-full bg-primary transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}

      {/* Log feed */}
      <div className="bg-bg/60 rounded-md border border-border max-h-60 overflow-y-auto">
        <ol className="divide-y divide-border text-xs font-mono">
          {log.length === 0 && (
            <li className="px-3 py-2 text-fg-muted italic">…</li>
          )}
          {log
            .slice()
            .reverse()
            .map((event, idx) => (
              <LogLine key={`${event.elapsed_seconds}-${idx}`} event={event} />
            ))}
        </ol>
      </div>
    </div>
  );
}

function LogLine({ event }: { event: ProgressEvent }) {
  const phaseColor: Record<Phase, string> = {
    idle: "text-fg-subtle",
    checking: "text-info",
    downloading: "text-primary",
    installing: "text-accent",
    rebooting: "text-warning",
    done: "text-success",
    error: "text-danger",
  };
  return (
    <li className="px-3 py-1.5 flex items-start gap-2">
      <span className="text-fg-subtle flex-shrink-0">
        [{event.elapsed_seconds.toFixed(1).padStart(5, " ")}s]
      </span>
      <span className={cn("font-bold flex-shrink-0", phaseColor[event.phase])}>
        {event.phase}
      </span>
      <span className="text-fg flex-1 break-all">{event.message}</span>
    </li>
  );
}

function UpdatesTable({
  updates,
  selectedIds,
  allSelected,
  onToggleAll,
  onToggleOne,
  disabled,
}: {
  updates: UpdateRow[];
  selectedIds: Set<string>;
  allSelected: boolean;
  onToggleAll: () => void;
  onToggleOne: (id: string) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="card !p-0 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">{t("updates.title")}</caption>
          <thead className="bg-surface-2 text-xs font-bold text-fg-muted">
            <tr>
              <th scope="col" className="px-4 py-3">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={onToggleAll}
                  disabled={disabled}
                  aria-label={t("updates.col.select")}
                />
              </th>
              <th scope="col" className="px-4 py-3 text-start">{t("updates.col.title")}</th>
              <th scope="col" className="px-4 py-3 text-start">{t("updates.col.kb")}</th>
              <th scope="col" className="px-4 py-3 text-start">{t("updates.col.severity")}</th>
              <th scope="col" className="px-4 py-3 text-start">{t("updates.col.size")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {updates.map((u) => (
              <UpdateRow
                key={u.update_id}
                update={u}
                checked={selectedIds.has(u.update_id)}
                onToggle={() => onToggleOne(u.update_id)}
                disabled={disabled}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function UpdateRow({
  update,
  checked,
  onToggle,
  disabled,
}: {
  update: UpdateRow;
  checked: boolean;
  onToggle: () => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const sevClass =
    update.severity === "Critical"
      ? "badge-danger"
      : update.severity === "Important"
        ? "badge-warning"
        : update.severity === "Moderate"
          ? "badge-info"
          : "";
  return (
    <tr className={cn(checked && "bg-primary-soft/30")}>
      <td className="px-4 py-3">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          disabled={disabled}
          aria-label={update.title}
        />
      </td>
      <td className="px-4 py-3 max-w-[420px]">
        <div className="font-medium truncate" title={update.title}>
          {update.title}
        </div>
        {update.requires_reboot && (
          <span className="inline-flex items-center gap-1 text-xs text-warning mt-0.5">
            <RotateCw className="w-3 h-3" />
            {t("updates.rebootRequired")}
          </span>
        )}
        {update.is_downloaded && (
          <span className="inline-flex items-center gap-1 text-xs text-success mt-0.5 ms-2">
            <CheckCircle2 className="w-3 h-3" />
            {t("updates.downloaded")}
          </span>
        )}
      </td>
      <td className="px-4 py-3 font-mono text-xs text-fg-muted" dir="ltr">
        {update.kb_articles.join(", ") || "—"}
      </td>
      <td className="px-4 py-3">
        {update.severity ? (
          <span className={cn("badge", sevClass)}>
            {t(`updates.severity.${update.severity}` as never, {
              defaultValue: update.severity,
            })}
          </span>
        ) : (
          "—"
        )}
      </td>
      <td className="px-4 py-3 font-mono text-xs whitespace-nowrap" dir="ltr">
        {update.size_mb > 0 ? `${update.size_mb.toFixed(1)} MB` : "—"}
      </td>
    </tr>
  );
}

function EmptyState({
  everChecked,
  onCheck,
  isChecking,
}: {
  everChecked: boolean;
  onCheck: () => void;
  isChecking: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="card text-center py-16">
      <div className="w-16 h-16 rounded-full bg-success/10 flex items-center justify-center mx-auto mb-4">
        <ShieldCheck className="w-8 h-8 text-success" />
      </div>
      <h3 className="text-xl font-display font-bold mb-2">
        {everChecked ? t("updates.upToDate") : t("updates.empty")}
      </h3>
      <p className="text-fg-muted mb-6 max-w-md mx-auto">
        {everChecked ? "" : t("updates.emptyHint")}
      </p>
      <button
        type="button"
        onClick={onCheck}
        disabled={isChecking}
        className="btn-primary inline-flex items-center gap-2"
      >
        {isChecking ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            {t("updates.checking")}
          </>
        ) : (
          <>
            <RefreshCw className="w-4 h-4" />
            {t("updates.check")}
          </>
        )}
      </button>
    </div>
  );
}
