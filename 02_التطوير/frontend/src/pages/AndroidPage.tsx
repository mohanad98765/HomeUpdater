import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  ArrowRight,
  Plus,
  Smartphone,
  RefreshCw,
  Trash2,
  Loader2,
  X,
  AlertTriangle,
  ExternalLink,
  Pencil,
  Link2,
  Check,
  Search,
} from "lucide-react";
import { apiFetch } from "@/lib/utils";
import { useLanguage } from "@/lib/language";

// ================================================================
// Types
// ================================================================
interface AndroidDevice {
  id: number;
  host: string;
  port: number;
  serial: string;
  manufacturer: string;
  model: string;
  brand: string;
  android_version: string;
  sdk_version: string;
  security_patch: string;
  custom_name: string;
  is_online: boolean;
  display_name: string;
  first_seen: string | null;
  last_seen: string | null;
}
interface DevicesList {
  devices: AndroidDevice[];
  total: number;
}
interface AppInfo {
  package_name: string;
  version_name: string;
  version_code: string;
  apk_path: string;
  label: string;
}
interface AppsList {
  device: AndroidDevice;
  apps: AppInfo[];
  total: number;
}

// ================================================================
// Page
// ================================================================
export function AndroidPage({ onBack }: { onBack: () => void }) {
  const { t } = useTranslation();
  const { dir } = useLanguage();
  const qc = useQueryClient();

  const [showAdd, setShowAdd] = useState(false);
  const [viewingApps, setViewingApps] = useState<AndroidDevice | null>(null);

  const list = useQuery<DevicesList>({
    queryKey: ["android-devices"],
    queryFn: () => apiFetch<DevicesList>("/api/android/devices"),
  });

  const remove = useMutation<{ deleted: number }, Error, number>({
    mutationFn: (id) =>
      apiFetch<{ deleted: number }>(`/api/android/devices/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["android-devices"] }),
  });

  const refresh = useMutation<AndroidDevice, Error, number>({
    mutationFn: (id) =>
      apiFetch<AndroidDevice>(`/api/android/devices/${id}/refresh`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["android-devices"] }),
  });

  const rename = useMutation<AndroidDevice, Error, { id: number; name: string }>({
    mutationFn: ({ id, name }) =>
      apiFetch<AndroidDevice>(`/api/android/devices/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ custom_name: name }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["android-devices"] }),
  });

  const BackIcon = dir === "rtl" ? ArrowRight : ArrowLeft;
  const devices = list.data?.devices ?? [];

  if (viewingApps) {
    return <AppsView device={viewingApps} onBack={() => setViewingApps(null)} />;
  }

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      {/* Header */}
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
          <h2 className="text-2xl font-display font-bold">{t("android.title")}</h2>
        </div>

        <button
          type="button"
          onClick={() => setShowAdd(true)}
          className="btn-primary inline-flex items-center gap-2"
        >
          <Plus className="w-4 h-4" />
          {t("android.addPhone")}
        </button>
      </div>

      {/* Body */}
      {list.isLoading ? (
        <div className="card text-center py-12">
          <Loader2 className="w-8 h-8 animate-spin mx-auto mb-3 text-fg-muted" />
        </div>
      ) : devices.length === 0 ? (
        <EmptyState onAdd={() => setShowAdd(true)} />
      ) : (
        <div className="grid gap-4">
          {devices.map((d) => (
            <DeviceCard
              key={d.id}
              device={d}
              onViewApps={() => setViewingApps(d)}
              onRefresh={() => refresh.mutate(d.id)}
              onRemove={() => {
                if (window.confirm(t("android.removeConfirm"))) remove.mutate(d.id);
              }}
              onRename={() => {
                const name = window.prompt(t("android.renamePrompt"), d.custom_name);
                if (name !== null) rename.mutate({ id: d.id, name });
              }}
              isRefreshing={refresh.isPending && refresh.variables === d.id}
              isRemoving={remove.isPending && remove.variables === d.id}
            />
          ))}
        </div>
      )}

      {/* Add dialog */}
      {showAdd && (
        <AddDeviceDialog
          onClose={() => setShowAdd(false)}
          onAdded={() => {
            setShowAdd(false);
            qc.invalidateQueries({ queryKey: ["android-devices"] });
          }}
        />
      )}
    </div>
  );
}

// ================================================================
// Subcomponents
// ================================================================
function EmptyState({ onAdd }: { onAdd: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="card text-center py-16">
      <div className="w-16 h-16 rounded-full bg-success/10 flex items-center justify-center mx-auto mb-4">
        <Smartphone className="w-8 h-8 text-success" />
      </div>
      <h3 className="text-xl font-display font-bold mb-2">{t("android.empty")}</h3>
      <p className="text-fg-muted mb-6 max-w-md mx-auto">{t("android.emptyHint")}</p>
      <button
        type="button"
        onClick={onAdd}
        className="btn-primary inline-flex items-center gap-2"
      >
        <Plus className="w-4 h-4" />
        {t("android.addPhone")}
      </button>
    </div>
  );
}

function DeviceCard({
  device,
  onViewApps,
  onRefresh,
  onRemove,
  onRename,
  isRefreshing,
  isRemoving,
}: {
  device: AndroidDevice;
  onViewApps: () => void;
  onRefresh: () => void;
  onRemove: () => void;
  onRename: () => void;
  isRefreshing: boolean;
  isRemoving: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="card flex items-start gap-4 flex-wrap">
      <div className="w-14 h-14 rounded-xl bg-success/10 text-success flex items-center justify-center flex-shrink-0">
        <Smartphone className="w-7 h-7" />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <h3 className="font-bold text-lg truncate">{device.display_name}</h3>
          <button
            type="button"
            onClick={onRename}
            className="text-fg-muted hover:text-primary transition-colors"
            title={t("android.rename")}
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
          {device.is_online ? (
            <span className="badge badge-success">{t("android.online")}</span>
          ) : (
            <span className="badge badge-danger">{t("android.offline")}</span>
          )}
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm mt-3">
          <InfoCell label={t("android.col.host")} value={`${device.host}:${device.port}`} />
          <InfoCell
            label={t("android.col.android")}
            value={`${device.android_version} (SDK ${device.sdk_version})`}
          />
          <InfoCell label={t("android.col.patch")} value={device.security_patch || "—"} />
          <InfoCell label="Serial" value={device.serial || "—"} />
        </div>
      </div>

      <div className="flex flex-col gap-2 flex-shrink-0">
        <button
          type="button"
          onClick={onViewApps}
          className="btn-primary inline-flex items-center gap-2 text-sm !py-1.5"
        >
          <Smartphone className="w-4 h-4" />
          {t("android.viewApps")}
        </button>
        <button
          type="button"
          onClick={onRefresh}
          disabled={isRefreshing}
          className="btn-secondary inline-flex items-center gap-2 text-sm !py-1.5"
        >
          {isRefreshing ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <RefreshCw className="w-4 h-4" />
          )}
          {t("android.refresh")}
        </button>
        <button
          type="button"
          onClick={onRemove}
          disabled={isRemoving}
          className="btn-secondary inline-flex items-center gap-2 text-sm !py-1.5 text-danger"
        >
          {isRemoving ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Trash2 className="w-4 h-4" />
          )}
          {t("android.remove")}
        </button>
      </div>
    </div>
  );
}

function InfoCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-fg-muted mb-0.5">{label}</div>
      <div className="font-mono text-sm truncate" dir="ltr" title={value}>
        {value}
      </div>
    </div>
  );
}

// ----------------------------------------------------------------
function AddDeviceDialog({
  onClose,
  onAdded,
}: {
  onClose: () => void;
  onAdded: () => void;
}) {
  const { t } = useTranslation();
  const [host, setHost] = useState("");
  const [pairPort, setPairPort] = useState("");
  const [code, setCode] = useState("");
  const [port, setPort] = useState(5555);

  const ipOk = /^\d{1,3}(\.\d{1,3}){3}$/.test(host.trim());

  const pairMut = useMutation<{ paired: boolean; connect_port: number | null }, Error>({
    mutationFn: () =>
      apiFetch<{ paired: boolean; connect_port: number | null }>("/api/android/pair", {
        method: "POST",
        body: JSON.stringify({
          host: host.trim(),
          port: parseInt(pairPort) || 0,
          code: code.trim(),
        }),
      }),
    onSuccess: (data) => {
      // Auto-fill the (different, random) connect port when mDNS found it.
      if (data.connect_port) setPort(data.connect_port);
    },
  });

  const discoverMut = useMutation<{ connect_port: number }, Error>({
    mutationFn: () =>
      apiFetch<{ connect_port: number }>("/api/android/discover", {
        method: "POST",
        body: JSON.stringify({ host: host.trim() }),
      }),
    onSuccess: (data) => {
      if (data.connect_port) setPort(data.connect_port);
    },
  });

  const add = useMutation<AndroidDevice, Error>({
    mutationFn: () =>
      apiFetch<AndroidDevice>("/api/android/devices", {
        method: "POST",
        body: JSON.stringify({ host: host.trim(), port }),
      }),
    onSuccess: () => onAdded(),
  });

  const canPair = ipOk && /^\d{2,5}$/.test(pairPort.trim()) && /^\d{6}$/.test(code.trim());
  const canSubmit = ipOk && port > 0;

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none overflow-y-auto">
        <div className="card w-full max-w-md pointer-events-auto my-8">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-bold text-lg">{t("android.addDialog.title")}</h3>
            <button
              type="button"
              onClick={onClose}
              className="p-1 rounded-md hover:bg-surface-2 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          <p className="text-sm text-fg-muted mb-3">{t("android.addDialog.hint")}</p>

          <div className="mb-4 p-3 rounded-md bg-info/10 border border-info/30 text-xs text-fg-muted space-y-2">
            <div className="font-bold text-info">كيف أربط جوّالي؟</div>
            <div>
              <b>Android 11 فأحدث (لاسلكي):</b> الإعدادات ← خيارات المطوّر ←{" "}
              <span dir="ltr">Wireless debugging</span> (فعّله). للربط أوّل مرّة اضغط{" "}
              <b>«إقران جهاز برمز الإقران»</b> — انسخ <span dir="ltr">IP:المنفذ</span> والرمز
              (٦ أرقام) إلى قسم «الإقران» أدناه واضغط <b>«إقران»</b>. ثم من الشاشة الرئيسية للتصحيح
              اللاسلكي خذ <span dir="ltr">IP:المنفذ</span> (
              <span className="text-warning">منفذ مختلف عن الإقران، ويتغيّر كل مرّة</span>) وأدخله في
              «منفذ الاتصال» واضغط «إضافة هاتف».
            </div>
            <div>
              <b>أقدم أو عبر USB:</b> شغّل <span dir="ltr" className="font-mono">adb tcpip 5555</span>{" "}
              مرّة، ثم استخدم IP الهاتف مع المنفذ{" "}
              <span dir="ltr" className="font-mono">5555</span> مباشرةً (بلا إقران).
            </div>
          </div>

          {/* Phone IP (shared by pairing + connecting) */}
          <div className="mb-3">
            <label className="text-xs font-bold text-fg-muted mb-1 block">
              {t("android.addDialog.ipLabel")}
            </label>
            <input
              type="text"
              dir="ltr"
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder={t("android.addDialog.ipPlaceholder")}
              className="w-full px-3 py-2 rounded-md border border-border bg-bg text-fg focus:border-primary focus:outline-none font-mono"
            />
          </div>

          {/* Pairing (Android 11+, one-time) */}
          <div className="mb-3 p-3 rounded-md border border-border bg-surface-2/40 space-y-2">
            <div className="flex items-center gap-2 text-xs font-bold text-fg">
              <Link2 className="w-4 h-4 text-primary" />
              الإقران (لاسلكي · Android 11+ · مرّة واحدة)
            </div>
            <div className="flex gap-2">
              <div className="flex-1">
                <label className="text-[11px] text-fg-muted mb-1 block">منفذ الإقران</label>
                <input
                  type="text"
                  dir="ltr"
                  inputMode="numeric"
                  value={pairPort}
                  onChange={(e) => setPairPort(e.target.value.replace(/[^\d]/g, ""))}
                  placeholder="37123"
                  className="w-full px-3 py-2 rounded-md border border-border bg-bg text-fg focus:border-primary focus:outline-none font-mono text-sm"
                />
              </div>
              <div className="flex-1">
                <label className="text-[11px] text-fg-muted mb-1 block">رمز الإقران (٦ أرقام)</label>
                <input
                  type="text"
                  dir="ltr"
                  inputMode="numeric"
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/[^\d]/g, ""))}
                  placeholder="123456"
                  className="w-full px-3 py-2 rounded-md border border-border bg-bg text-fg focus:border-primary focus:outline-none font-mono text-sm"
                />
              </div>
            </div>
            <button
              type="button"
              onClick={() => pairMut.mutate()}
              disabled={!canPair || pairMut.isPending}
              className="btn-secondary w-full inline-flex items-center justify-center gap-2 text-sm"
            >
              {pairMut.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  جارٍ الإقران…
                </>
              ) : (
                <>
                  <Link2 className="w-4 h-4" />
                  إقران
                </>
              )}
            </button>
            {pairMut.isSuccess && (
              <div className="text-xs text-success inline-flex items-center gap-1">
                <Check className="w-3.5 h-3.5" />
                {pairMut.data?.connect_port
                  ? `تمّ الإقران واكتُشف منفذ الاتصال (${pairMut.data.connect_port}) — اضغط «إضافة هاتف».`
                  : "تمّ الإقران — الآن اكتشف منفذ الاتصال أو أدخله يدوياً، ثم أضِف الهاتف."}
              </div>
            )}
            {pairMut.isError && (
              <div className="text-xs text-danger font-mono break-all">
                {(pairMut.error as Error).message}
              </div>
            )}
          </div>

          {/* Connect port + auto-discover + add */}
          <div className="mb-2">
            <label className="text-xs font-bold text-fg-muted mb-1 block">
              {t("android.addDialog.portLabel")}
            </label>
            <div className="flex gap-2">
              <input
                type="number"
                dir="ltr"
                value={port}
                onChange={(e) => setPort(parseInt(e.target.value) || 5555)}
                className="flex-1 px-3 py-2 rounded-md border border-border bg-bg text-fg focus:border-primary focus:outline-none font-mono"
              />
              <button
                type="button"
                onClick={() => discoverMut.mutate()}
                disabled={!ipOk || discoverMut.isPending}
                title="اكتشف منفذ الاتصال تلقائياً (mDNS)"
                className="btn-secondary inline-flex items-center gap-1 whitespace-nowrap text-sm"
              >
                {discoverMut.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Search className="w-4 h-4" />
                )}
                اكتشف المنفذ
              </button>
            </div>
            {discoverMut.isError && (
              <div className="mt-1 text-xs text-danger">{(discoverMut.error as Error).message}</div>
            )}
          </div>

          <div className="mt-4 p-3 rounded-md bg-info/10 border border-info/30 text-info text-xs">
            {t("android.addDialog.firstTimeNote")}
          </div>

          {add.isError && (
            <div className="mt-3 p-3 rounded-md bg-danger/10 border border-danger/30 text-danger text-sm flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span className="font-mono text-xs break-all">{(add.error as Error).message}</span>
            </div>
          )}

          <div className="mt-5 flex items-center justify-end gap-2">
            <button type="button" onClick={onClose} className="btn-secondary">
              {t("detail.cancel")}
            </button>
            <button
              type="button"
              onClick={() => add.mutate()}
              disabled={!canSubmit || add.isPending}
              className="btn-primary inline-flex items-center gap-2"
            >
              {add.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {t("android.addDialog.connecting")}
                </>
              ) : (
                <>
                  <Plus className="w-4 h-4" />
                  {t("android.addPhone")}
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

// ----------------------------------------------------------------
function AppsView({
  device,
  onBack,
}: {
  device: AndroidDevice;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const { dir } = useLanguage();
  const qc = useQueryClient();

  const apps = useQuery<AppsList>({
    queryKey: ["android-apps", device.id],
    queryFn: () => apiFetch<AppsList>(`/api/android/devices/${device.id}/apps`),
  });

  const openStore = useMutation<unknown, Error, string>({
    mutationFn: (pkg) =>
      apiFetch(`/api/android/devices/${device.id}/apps/${encodeURIComponent(pkg)}/open`, {
        method: "POST",
      }),
  });

  const BackIcon = dir === "rtl" ? ArrowRight : ArrowLeft;
  const list = apps.data?.apps ?? [];

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onBack}
            className="btn-secondary inline-flex items-center gap-2"
          >
            <BackIcon className="w-4 h-4" />
            {t("android.apps.back")}
          </button>
          <div>
            <h2 className="text-xl font-display font-bold">
              {t("android.apps.title", { name: device.display_name })}
            </h2>
            <p className="text-xs text-fg-muted font-mono" dir="ltr">
              {device.host}:{device.port} · Android {device.android_version}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => qc.invalidateQueries({ queryKey: ["android-apps", device.id] })}
          disabled={apps.isFetching}
          className="btn-secondary inline-flex items-center gap-2"
        >
          {apps.isFetching ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <RefreshCw className="w-4 h-4" />
          )}
          {t("android.apps.refresh")}
        </button>
      </div>

      {apps.isLoading ? (
        <div className="card text-center py-12">
          <Loader2 className="w-8 h-8 animate-spin mx-auto mb-3 text-fg-muted" />
        </div>
      ) : apps.isError ? (
        <div className="card p-4 border-danger/30 bg-danger/10 text-danger">
          <p className="font-bold mb-1">{(apps.error as Error).message}</p>
        </div>
      ) : list.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-fg-muted">{t("android.apps.empty")}</p>
        </div>
      ) : (
        <div className="card !p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-2 text-xs font-bold text-fg-muted">
                <tr>
                  <th className="px-4 py-3 text-start">{t("android.apps.package")}</th>
                  <th className="px-4 py-3 text-start">{t("android.apps.version")}</th>
                  <th className="px-2 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {list.map((app) => (
                  <tr key={app.package_name} className="hover:bg-surface-2/50">
                    <td className="px-4 py-3">
                      <div className="font-mono text-sm truncate max-w-[420px]" dir="ltr">
                        {app.package_name}
                      </div>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-fg-muted" dir="ltr">
                      {app.version_name || "—"}
                      {app.version_code && (
                        <span className="text-fg-subtle"> ({app.version_code})</span>
                      )}
                    </td>
                    <td className="px-2 py-3">
                      <button
                        type="button"
                        onClick={() => openStore.mutate(app.package_name)}
                        disabled={openStore.isPending}
                        title={t("android.apps.openStoreHint")}
                        className="btn-secondary !py-1 !px-2 inline-flex items-center gap-1 text-xs"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                        {t("android.apps.openStore")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
