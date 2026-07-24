import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  RefreshCw,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  Download,
  Activity,
  ShieldCheck,
  Package,
} from "lucide-react";
import { apiFetch, cn } from "@/lib/utils";

// ================================================================
// Phase 1.5 — Software (winget) updates view
// Embedded inside the Updates page; behavior mirrors the Windows view.
// ================================================================

interface PackageRow {
  id: number;
  package_id: string;
  name: string;
  current_version: string;
  available_version: string;
  source: string;
  size_mb: number;
  is_installed: boolean;
  install_result: number;
  last_checked: string | null;
}
interface PackagesList {
  pending: PackageRow[];
  total_pending: number;
  last_checked: string | null;
}
interface InstallResponse {
  installed: number;
  total: number;
  results: Array<{ package_id: string; succeeded: boolean; exit_code: number }>;
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

export function SoftwareUpdatesView() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const list = useQuery<PackagesList>({
    queryKey: ["software-updates"],
    queryFn: () => apiFetch<PackagesList>("/api/updates/software"),
  });

  const check = useMutation({
    mutationFn: () =>
      apiFetch("/api/updates/software/check", { method: "POST", body: JSON.stringify({}) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["software-updates"] });
      setSelected(new Set());
    },
  });

  const install = useMutation<InstallResponse>({
    mutationFn: () =>
      apiFetch<InstallResponse>("/api/updates/software/install", {
        method: "POST",
        body: JSON.stringify({ package_ids: Array.from(selected) }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["software-updates"] });
      setSelected(new Set());
    },
  });

  const progress = useQuery<ProgressState>({
    queryKey: ["update-status"],
    queryFn: () => apiFetch<ProgressState>("/api/updates/windows/status"),
    enabled: check.isPending || install.isPending,
    refetchInterval: 1000,
  });

  const pending = list.data?.pending ?? [];
  const allSelected = pending.length > 0 && pending.every((p) => selected.has(p.package_id));
  const toggleAll = () => {
    if (allSelected) setSelected(new Set());
    else setSelected(new Set(pending.map((p) => p.package_id)));
  };
  const toggleOne = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const onInstallClick = () => {
    const count = selected.size || pending.length;
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
          <h2 className="text-xl font-display font-bold">{t("software.title")}</h2>
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
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
            {check.isPending ? t("updates.checking") : t("updates.check")}
          </button>

          {pending.length > 0 && (
            <button
              type="button"
              onClick={onInstallClick}
              disabled={install.isPending || check.isPending}
              className="btn-primary inline-flex items-center gap-2"
            >
              {install.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Download className="w-4 h-4" />
              )}
              {selected.size > 0 ? t("updates.install") : t("updates.installAll")}
            </button>
          )}
        </div>
      </div>

      {/* Stat row */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
        <Tile
          icon={Package}
          label={t("updates.pending", { count: pending.length })}
          value={pending.length.toString()}
          accent={pending.length > 0 ? "warning" : "success"}
        />
      </div>

      {/* Progress */}
      {(check.isPending || install.isPending || progress.data?.is_running) && (
        <ProgressCard progress={progress.data} />
      )}

      {/* Install summary — green only when every package installed; a partial
          result (installed < total) must surface as a warning, not fake success. */}
      {install.data && !install.isPending && (
        <div
          className={cn(
            "mb-6 p-4 rounded-lg border flex items-start gap-3",
            install.data.installed === install.data.total
              ? "border-success/30 bg-success/10 text-success"
              : "border-warning/30 bg-warning/10 text-warning"
          )}
        >
          {install.data.installed === install.data.total ? (
            <CheckCircle2 className="w-5 h-5 flex-shrink-0 mt-0.5" />
          ) : (
            <AlertTriangle className="w-5 h-5 flex-shrink-0 mt-0.5" />
          )}
          <p className="font-bold">
            {t("updates.installSuccess", {
              installed: install.data.installed,
              total: install.data.total,
            })}
          </p>
        </div>
      )}

      {/* Errors — friendly framing + a one-click retry. */}
      {(check.isError || install.isError) && (
        <div className="mb-6 p-4 rounded-lg border border-danger/30 bg-danger/10 text-danger">
          <div className="flex items-start gap-3 flex-wrap">
            <AlertTriangle className="w-5 h-5 flex-shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <p className="font-bold mb-1">
                {t(check.isError ? "updates.checkFailed" : "updates.installFailed")}
              </p>
              <p className="text-sm mb-1">{t("updates.transientHint")}</p>
              {(check.error || install.error) instanceof Error && (
                <p className="text-xs font-mono text-danger/80 break-words">
                  {(check.error || install.error)!.message}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={() => (check.isError ? check.mutate() : install.mutate())}
              disabled={check.isPending || install.isPending}
              className="btn-secondary text-sm inline-flex items-center gap-2 flex-shrink-0"
            >
              <RefreshCw className="w-4 h-4" />
              {t("updates.retry")}
            </button>
          </div>
        </div>
      )}

      {/* Body */}
      {list.isLoading ? (
        <div className="card text-center py-12">
          <Loader2 className="w-8 h-8 animate-spin mx-auto mb-3 text-fg-muted" />
        </div>
      ) : pending.length === 0 ? (
        <Empty
          everChecked={!!list.data?.last_checked}
          onCheck={() => check.mutate()}
          isChecking={check.isPending}
        />
      ) : (
        <Table
          rows={pending}
          selected={selected}
          allSelected={allSelected}
          onToggleAll={toggleAll}
          onToggleOne={toggleOne}
          disabled={install.isPending}
        />
      )}
    </div>
  );
}

// ----------------------------------------------------------------
function Tile({
  icon: Icon,
  label,
  value,
  accent,
}: {
  icon: typeof Package;
  label: string;
  value: string;
  accent: "warning" | "success" | "info";
}) {
  const colors: Record<string, string> = {
    warning: "bg-warning/10 text-warning",
    success: "bg-success/10 text-success",
    info: "bg-info/10 text-info",
  };
  return (
    <div className="card !p-4 flex items-center gap-3">
      <div className={cn("w-10 h-10 rounded-lg flex items-center justify-center", colors[accent])}>
        <Icon className="w-5 h-5" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-xs text-fg-muted truncate">{label}</div>
        <div className="text-xl font-display font-bold tabular-nums">{value}</div>
      </div>
    </div>
  );
}

function ProgressCard({ progress }: { progress: ProgressState | undefined }) {
  const { t } = useTranslation();
  if (!progress) return null;
  const elapsed = progress.elapsed_seconds;
  const log = progress.log ?? [];
  const pct =
    progress.total > 0 ? Math.min(100, (progress.completed / progress.total) * 100) : 0;
  return (
    <div className="card mb-6 border-primary/30 bg-primary-soft/30">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-primary animate-pulse" />
          <h3 className="font-bold">
            {t(`updates.progress.${progress.phase}` as never, { defaultValue: progress.phase })}
          </h3>
        </div>
        <span className="font-mono text-primary font-bold text-sm">{elapsed.toFixed(1)}s</span>
      </div>
      {progress.total > 0 && (
        <div className="h-2 bg-bg/60 rounded-full overflow-hidden mb-3">
          <div
            className="h-full bg-primary transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
      <div className="bg-bg/60 rounded-md border border-border max-h-60 overflow-y-auto">
        <ol className="divide-y divide-border text-xs font-mono">
          {log
            .slice()
            .reverse()
            .map((event, idx) => (
              <li key={idx} className="px-3 py-1.5 flex items-start gap-2">
                <span className="text-fg-subtle flex-shrink-0">
                  [{event.elapsed_seconds.toFixed(1).padStart(5, " ")}s]
                </span>
                <span className="font-bold text-primary flex-shrink-0">{event.phase}</span>
                <span className="text-fg flex-1 break-all">{event.message}</span>
              </li>
            ))}
        </ol>
      </div>
    </div>
  );
}

function Table({
  rows,
  selected,
  allSelected,
  onToggleAll,
  onToggleOne,
  disabled,
}: {
  rows: PackageRow[];
  selected: Set<string>;
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
          <caption className="sr-only">{t("software.title")}</caption>
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
              <th scope="col" className="px-4 py-3 text-start">{t("software.col.name")}</th>
              <th scope="col" className="px-4 py-3 text-start">{t("software.col.packageId")}</th>
              <th scope="col" className="px-4 py-3 text-start">{t("software.col.current")}</th>
              <th scope="col" className="px-4 py-3 text-start">{t("software.col.available")}</th>
              <th scope="col" className="px-4 py-3 text-start">{t("software.col.source")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((p) => {
              const checked = selected.has(p.package_id);
              return (
                <tr
                  key={p.package_id}
                  className={cn(checked && "bg-primary-soft/30")}
                >
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => onToggleOne(p.package_id)}
                      disabled={disabled}
                      aria-label={p.name || p.package_id}
                    />
                  </td>
                  <td className="px-4 py-3 max-w-[300px]">
                    <div className="font-medium truncate" title={p.name}>
                      {p.name || p.package_id}
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-fg-muted" dir="ltr">
                    {p.package_id}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs" dir="ltr">
                    {p.current_version}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-success" dir="ltr">
                    {p.available_version}
                  </td>
                  <td className="px-4 py-3 text-xs text-fg-muted">{p.source}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Empty({
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
        {everChecked ? t("software.empty") : t("updates.empty")}
      </h3>
      <p className="text-fg-muted mb-6 max-w-md mx-auto">{t("software.emptyHint")}</p>
      <button
        type="button"
        onClick={onCheck}
        disabled={isChecking}
        className="btn-primary inline-flex items-center gap-2"
      >
        {isChecking ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <RefreshCw className="w-4 h-4" />
        )}
        {t("updates.check")}
      </button>
    </div>
  );
}
