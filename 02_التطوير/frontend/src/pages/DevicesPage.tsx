import { useState, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  ArrowRight,
  RefreshCw,
  Loader2,
  AlertTriangle,
  Wifi,
  Network as NetworkIcon,
  Activity,
  Pencil,
  Check,
  X,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { apiFetch, cn } from "@/lib/utils";
import { DeviceTypeIcon } from "@/components/DeviceTypeIcon";
import { useLanguage } from "@/lib/language";
import { StatsCards, type DeviceStats } from "@/components/StatsCards";
import {
  DeviceDetailPanel,
  type Device as PanelDevice,
} from "@/components/DeviceDetailPanel";

// ================================================================
// Types
// ================================================================
type Device = PanelDevice; // share the same shape

interface DeviceList {
  devices: Device[];
  total: number;
  subnet: string;
}

interface ScanResponse extends DeviceList {
  new: number;
  duration_seconds: number;
  timestamp: string;
}

interface NetworkInfo {
  local_ip: string | null;
  netmask: string | null;
  raw_subnet: string | null;
  suggested_subnet: string;
  gateway_ip: string | null;
  interface_name: string | null;
  interfaces: Array<{ name: string; ip: string; netmask: string }>;
  stored_devices: number;
}

type Phase =
  | "idle"
  | "detecting"
  | "scanning"
  | "resolving"
  | "classifying"
  | "done"
  | "error";

interface ProgressEvent {
  elapsed_seconds: number;
  phase: Phase;
  message: string;
}
interface ProgressState {
  is_running: boolean;
  phase: Phase;
  subnet: string;
  devices_count: number;
  elapsed_seconds: number;
  last_message: string;
  error: string | null;
  log: ProgressEvent[];
}

// ================================================================
// Page
// ================================================================
export function DevicesPage({ onBack }: { onBack: () => void }) {
  const { t } = useTranslation();
  const { dir } = useLanguage();
  const qc = useQueryClient();

  const [scanSubnet, setScanSubnet] = useState<string>("");
  const [editing, setEditing] = useState(false);
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null);

  const info = useQuery<NetworkInfo>({
    queryKey: ["network-info"],
    queryFn: () => apiFetch<NetworkInfo>("/api/devices/info"),
    staleTime: 30_000,
  });

  useEffect(() => {
    if (info.data && !scanSubnet) {
      setScanSubnet(info.data.raw_subnet || info.data.suggested_subnet || "");
    }
  }, [info.data, scanSubnet]);

  const list = useQuery<DeviceList>({
    queryKey: ["devices"],
    queryFn: () => apiFetch<DeviceList>("/api/devices"),
  });

  const stats = useQuery<DeviceStats>({
    queryKey: ["device-stats"],
    queryFn: () => apiFetch<DeviceStats>("/api/devices/stats"),
    refetchInterval: 30_000,
  });

  const scan = useMutation<ScanResponse>({
    mutationFn: () =>
      apiFetch<ScanResponse>("/api/devices/scan", {
        method: "POST",
        body: JSON.stringify({ subnet: scanSubnet || null }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      qc.invalidateQueries({ queryKey: ["device-stats"] });
    },
  });

  const progress = useQuery<ProgressState>({
    queryKey: ["scan-status"],
    queryFn: () => apiFetch<ProgressState>("/api/devices/scan/status"),
    enabled: scan.isPending,
    refetchInterval: 1000,
  });

  // Keep selected device fresh (so panel reflects latest data after a scan)
  const devices: Device[] = scan.data?.devices ?? list.data?.devices ?? [];
  useEffect(() => {
    if (selectedDevice) {
      const fresh = devices.find((d) => d.id === selectedDevice.id);
      if (fresh && fresh !== selectedDevice) setSelectedDevice(fresh);
    }
  }, [devices, selectedDevice]);

  const BackIcon = dir === "rtl" ? ArrowRight : ArrowLeft;

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      {/* Header bar */}
      <div className="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onBack}
            className="btn-secondary inline-flex items-center gap-2"
          >
            <BackIcon className="w-4 h-4" />
            <span className="hidden sm:inline">{t("nav.dashboard")}</span>
          </button>
          <h2 className="text-2xl font-display font-bold">{t("devices.title")}</h2>
        </div>

        <button
          type="button"
          onClick={() => scan.mutate()}
          disabled={scan.isPending || !scanSubnet}
          className="btn-primary inline-flex items-center gap-2"
        >
          {scan.isPending ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              {t("devices.scanning")}
            </>
          ) : (
            <>
              <RefreshCw className="w-4 h-4" />
              {t("devices.scan")}
            </>
          )}
        </button>
      </div>

      {/* Stats cards */}
      <StatsCards stats={stats.data} isLoading={stats.isLoading} />

      {/* Network info card */}
      <NetworkInfoCard
        info={info.data}
        scanSubnet={scanSubnet}
        editing={editing}
        onChangeSubnet={setScanSubnet}
        onStartEdit={() => setEditing(true)}
        onCancelEdit={() => {
          setEditing(false);
          if (info.data) setScanSubnet(info.data.raw_subnet || info.data.suggested_subnet || "");
        }}
        onApplyEdit={() => setEditing(false)}
      />

      {/* Live activity log (only while scanning) */}
      {(scan.isPending || progress.data?.is_running) && (
        <ActivityLog progress={progress.data} subnet={scanSubnet} />
      )}

      {/* Scan result summary */}
      {scan.data && !scan.isPending && (
        <div className="mb-6 p-4 rounded-lg border border-success/30 bg-success/10 text-success flex items-center gap-3 flex-wrap text-sm">
          <Wifi className="w-5 h-5 flex-shrink-0" />
          <span className="font-bold">{t("devices.total", { count: scan.data.total })}</span>
          {scan.data.new > 0 && (
            <span className="badge badge-info">
              {t("devices.new", { count: scan.data.new })}
            </span>
          )}
          <span className="text-fg-muted">
            {t("devices.duration", { seconds: scan.data.duration_seconds.toFixed(1) })}
          </span>
        </div>
      )}

      {/* Scan error */}
      {scan.isError && (
        <div className="mb-6 p-4 rounded-lg border border-danger/30 bg-danger/10 text-danger flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-bold mb-1">{t("devices.scanFailed")}</p>
            <p className="text-sm font-mono">{(scan.error as Error)?.message}</p>
          </div>
        </div>
      )}

      {/* Devices table or empty state */}
      {list.isLoading && !devices.length ? (
        <div className="card text-center py-12">
          <Loader2 className="w-8 h-8 animate-spin mx-auto mb-3 text-fg-muted" />
          <p className="text-fg-muted">{t("status.loading")}</p>
        </div>
      ) : devices.length === 0 && !scan.isPending ? (
        <EmptyState onScan={() => scan.mutate()} disabled={scan.isPending || !scanSubnet} />
      ) : devices.length > 0 ? (
        <DeviceTable
          devices={devices}
          onRowClick={(d) => setSelectedDevice(d)}
          selectedId={selectedDevice?.id}
        />
      ) : null}

      {/* Slide-in detail panel */}
      <DeviceDetailPanel device={selectedDevice} onClose={() => setSelectedDevice(null)} />
    </div>
  );
}

// ================================================================
// Network Info Card
// ================================================================
function NetworkInfoCard({
  info,
  scanSubnet,
  editing,
  onChangeSubnet,
  onStartEdit,
  onCancelEdit,
  onApplyEdit,
}: {
  info: NetworkInfo | undefined;
  scanSubnet: string;
  editing: boolean;
  onChangeSubnet: (v: string) => void;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onApplyEdit: () => void;
}) {
  const { t } = useTranslation();

  if (!info) {
    return (
      <div className="card mb-6">
        <Loader2 className="w-5 h-5 animate-spin text-fg-muted" />
      </div>
    );
  }

  const sizeOf = (cidr: string): number => {
    const m = /\/(\d+)$/.exec(cidr || "");
    if (!m) return 0;
    const prefix = parseInt(m[1], 10);
    return Math.pow(2, 32 - prefix) - 2;
  };
  const size = sizeOf(scanSubnet);
  const isLarge = size >= 1024;
  const isCidrValid = /^(\d{1,3}\.){3}\d{1,3}\/\d{1,2}$/.test(scanSubnet);

  return (
    <div className="card mb-6">
      <div className="flex items-center gap-2 mb-3">
        <NetworkIcon className="w-5 h-5 text-primary" />
        <h3 className="font-bold">{t("network.info")}</h3>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm mb-4">
        <InfoCell label={t("network.localIp")} value={info.local_ip || "—"} />
        <InfoCell label={t("network.gateway")} value={info.gateway_ip || "—"} />
        <InfoCell label={t("network.netmask")} value={info.netmask || "—"} />
        <InfoCell label={t("network.adapter")} value={info.interface_name || "—"} />
      </div>

      <div className="border-t border-border pt-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-3 flex-1 min-w-0">
            <span className="text-sm font-bold text-fg-muted whitespace-nowrap">
              {t("network.scanRange")}:
            </span>
            {editing ? (
              <div className="flex items-center gap-2 flex-1">
                <input
                  type="text"
                  dir="ltr"
                  value={scanSubnet}
                  onChange={(e) => onChangeSubnet(e.target.value)}
                  placeholder="192.168.1.0/24"
                  className={cn(
                    "px-3 py-1.5 rounded-md border bg-surface text-fg font-mono text-sm flex-1 max-w-xs",
                    isCidrValid ? "border-border focus:border-primary" : "border-danger"
                  )}
                />
                <button
                  type="button"
                  onClick={onApplyEdit}
                  disabled={!isCidrValid}
                  className="btn-primary !py-1.5 !px-2 inline-flex items-center gap-1 text-sm"
                  title={t("network.applyRange")}
                >
                  <Check className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  onClick={onCancelEdit}
                  className="btn-secondary !py-1.5 !px-2 inline-flex items-center gap-1 text-sm"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <>
                <span className="font-mono text-sm bg-surface-2 px-2 py-1 rounded" dir="ltr">
                  {scanSubnet || "—"}
                </span>
                <button
                  type="button"
                  onClick={onStartEdit}
                  className="text-fg-muted hover:text-primary transition-colors"
                  title={t("network.editRange")}
                >
                  <Pencil className="w-4 h-4" />
                </button>
              </>
            )}
          </div>

          {!editing && size > 0 && (
            <span className={cn("text-xs font-mono", isLarge ? "text-warning" : "text-fg-subtle")}>
              ≈ {size.toLocaleString()} IP
            </span>
          )}
        </div>

        {!isCidrValid && editing && (
          <p className="text-xs text-danger mt-2">{t("network.invalidCidr")}</p>
        )}

        {!editing && isLarge && (
          <p className="text-xs text-warning mt-3 flex items-start gap-2">
            <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
            <span>{t("network.largeNetworkWarning", { size: size.toLocaleString() })}</span>
          </p>
        )}

        {!editing &&
          info.suggested_subnet &&
          info.suggested_subnet !== scanSubnet &&
          isLarge && (
            <p className="text-xs text-fg-muted mt-2">
              {t("network.smallSubnetSuggestion", { suggested: info.suggested_subnet })}{" "}
              <button
                type="button"
                onClick={() => onChangeSubnet(info.suggested_subnet)}
                className="text-primary underline hover:no-underline"
              >
                {t("network.useSmaller")}
              </button>
            </p>
          )}
      </div>
    </div>
  );
}

function InfoCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-fg-muted mb-1">{label}</div>
      <div className="font-mono text-sm font-medium truncate" dir="ltr">
        {value}
      </div>
    </div>
  );
}

// ================================================================
// Activity Log
// ================================================================
function ActivityLog({
  progress,
  subnet,
}: {
  progress: ProgressState | undefined;
  subnet: string;
}) {
  const { t } = useTranslation();
  const elapsed = progress?.elapsed_seconds ?? 0;
  const count = progress?.devices_count ?? 0;
  const log = progress?.log ?? [];

  return (
    <div className="card mb-6 border-primary/30 bg-primary-soft/30">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-primary animate-pulse" />
          <h3 className="font-bold">{t("devices.scanning")}</h3>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="font-mono text-primary font-bold">
            {t("scanProgress.elapsed", { seconds: elapsed.toFixed(1) })}
          </span>
          <span className="badge badge-info">
            {t("devices.total", { count })}
          </span>
        </div>
      </div>

      <div className="text-xs text-fg-muted mb-3 font-mono" dir="ltr">
        {subnet}
      </div>

      <div className="bg-bg/60 rounded-md border border-border max-h-60 overflow-y-auto">
        <ol className="divide-y divide-border text-xs font-mono">
          {log.length === 0 && (
            <li className="px-3 py-2 text-fg-muted italic">{t("scanProgress.step1")}</li>
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
    detecting: "text-info",
    scanning: "text-primary",
    resolving: "text-accent",
    classifying: "text-warning",
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

// ================================================================
// Devices table
// ================================================================
function DeviceTable({
  devices,
  onRowClick,
  selectedId,
}: {
  devices: Device[];
  onRowClick: (d: Device) => void;
  selectedId?: number;
}) {
  const { t } = useTranslation();
  const { dir } = useLanguage();
  const Chevron = dir === "rtl" ? ChevronLeft : ChevronRight;

  return (
    <div className="card !p-0 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-surface-2 text-xs font-bold text-fg-muted">
            <tr>
              <th className="px-4 py-3 text-start">{t("devices.col.type")}</th>
              <th className="px-4 py-3 text-start">{t("devices.col.host")}</th>
              <th className="px-4 py-3 text-start">{t("devices.col.ip")}</th>
              <th className="px-4 py-3 text-start font-mono">{t("devices.col.mac")}</th>
              <th className="px-4 py-3 text-start">{t("devices.col.vendor")}</th>
              <th className="px-4 py-3 text-start">{t("devices.col.status")}</th>
              <th className="px-2 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {devices.map((d) => (
              <tr
                key={d.id}
                onClick={() => onRowClick(d)}
                className={cn(
                  "cursor-pointer transition-colors",
                  selectedId === d.id ? "bg-primary-soft/40" : "hover:bg-surface-2/50"
                )}
              >
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <DeviceTypeIcon type={d.device_type} size={4} />
                    <span className="text-xs">{t(`devices.type.${d.device_type}` as never)}</span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  {d.custom_name ? (
                    <div>
                      <span className="font-medium">{d.custom_name}</span>
                      {d.hostname && (
                        <span className="block text-xs text-fg-muted truncate">
                          {d.hostname}
                        </span>
                      )}
                    </div>
                  ) : d.hostname ? (
                    <span className="font-medium">{d.hostname}</span>
                  ) : (
                    <span className="text-fg-subtle italic">{t("devices.unknownHost")}</span>
                  )}
                </td>
                <td className="px-4 py-3 font-mono text-xs" dir="ltr">{d.ip}</td>
                <td className="px-4 py-3 font-mono text-xs text-fg-muted" dir="ltr">
                  {d.mac || "—"}
                </td>
                <td className="px-4 py-3 text-fg-muted truncate max-w-[180px]">
                  {d.vendor || "—"}
                </td>
                <td className="px-4 py-3">
                  {d.status === "online" ? (
                    <span className="badge badge-success">{t("status.online")}</span>
                  ) : (
                    <span className="badge badge-danger">{t("status.offline")}</span>
                  )}
                </td>
                <td className="px-2 py-3 text-fg-subtle">
                  <Chevron className="w-4 h-4" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EmptyState({ onScan, disabled }: { onScan: () => void; disabled: boolean }) {
  const { t } = useTranslation();
  return (
    <div className="card text-center py-16">
      <div className="w-16 h-16 rounded-full bg-primary-soft flex items-center justify-center mx-auto mb-4">
        <Wifi className="w-8 h-8 text-primary" />
      </div>
      <h3 className="text-xl font-display font-bold mb-2">{t("devices.empty")}</h3>
      <p className="text-fg-muted mb-6 max-w-md mx-auto">{t("devices.emptyHint")}</p>
      <button
        type="button"
        onClick={onScan}
        disabled={disabled}
        className="btn-primary inline-flex items-center gap-2"
      >
        <RefreshCw className="w-4 h-4" />
        {t("devices.scan")}
      </button>
    </div>
  );
}
