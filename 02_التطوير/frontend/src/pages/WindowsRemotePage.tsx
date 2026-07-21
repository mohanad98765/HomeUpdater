import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  ArrowRight,
  Loader2,
  MonitorSmartphone,
  Plus,
  Trash2,
  RefreshCw,
  Download,
  CheckCircle2,
  ShieldCheck,
  Info,
  Server,
} from "lucide-react";
import { apiFetch } from "@/lib/utils";
import { useLanguage } from "@/lib/language";

// ================================================================
// صفحة أجهزة Windows البعيدة — تحديث عبر WinRM/winget (المرحلة 1.6)
// ================================================================

interface WinRMHost {
  id: number;
  host: string;
  port: number;
  username: string;
  use_https: boolean;
  verify_tls: boolean;
  transport: string;
  custom_name: string;
  os_name: string;
  os_version: string;
  hostname: string;
  has_winget: boolean;
  is_online: boolean;
  display_name: string;
}
interface UpdateCheck {
  total: number;
  packages: { name: string; id: string; current: string; available: string }[];
}

export function WindowsRemotePage({ onBack }: { onBack: () => void }) {
  const { t } = useTranslation();
  const { dir } = useLanguage();
  const qc = useQueryClient();
  const BackIcon = dir === "rtl" ? ArrowRight : ArrowLeft;

  const hosts = useQuery<{ hosts: WinRMHost[]; total: number }>({
    queryKey: ["winrm-hosts"],
    queryFn: () => apiFetch("/api/winrm/hosts"),
  });

  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    host: "",
    port: 5985,
    username: "",
    password: "",
    use_https: false,
    verify_tls: false,
    custom_name: "",
  });
  const [checks, setChecks] = useState<Record<number, UpdateCheck>>({});
  const [upgradeResults, setUpgradeResults] = useState<
    Record<number, { succeeded: boolean; output_tail: string }>
  >({});

  const add = useMutation({
    mutationFn: () => apiFetch("/api/winrm/hosts", { method: "POST", body: JSON.stringify(form) }),
    onSuccess: () => {
      setShowForm(false);
      setForm({
        host: "",
        port: 5985,
        username: "",
        password: "",
        use_https: false,
        verify_tls: false,
        custom_name: "",
      });
      qc.invalidateQueries({ queryKey: ["winrm-hosts"] });
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => apiFetch(`/api/winrm/hosts/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["winrm-hosts"] }),
  });

  const check = useMutation<UpdateCheck, Error, number>({
    mutationFn: (id) =>
      apiFetch<UpdateCheck>(`/api/winrm/hosts/${id}/check`, { method: "POST", body: "{}" }),
    onSuccess: (data, id) => setChecks((c) => ({ ...c, [id]: data })),
  });

  const upgrade = useMutation<{ succeeded: boolean; output_tail: string }, Error, number>({
    mutationFn: (id: number) =>
      apiFetch(`/api/winrm/hosts/${id}/upgrade`, { method: "POST", body: "{}" }),
    onSuccess: (data, id) => {
      setUpgradeResults((r) => ({ ...r, [id]: data }));
      check.mutate(id);
    },
  });

  const list = hosts.data?.hosts ?? [];

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <button type="button" onClick={onBack} className="btn-secondary inline-flex items-center gap-2">
          <BackIcon className="w-4 h-4" />
          <span className="hidden sm:inline">{t("nav.dashboard")}</span>
        </button>
        <div className="flex items-center gap-2">
          <MonitorSmartphone className="w-5 h-5 text-primary" />
          <h2 className="text-xl font-display font-bold">{t("pages.winrm.title")}</h2>
        </div>
        <button
          type="button"
          onClick={() => setShowForm((s) => !s)}
          className="btn-primary inline-flex items-center gap-2"
        >
          <Plus className="w-4 h-4" /> {t("pages.remote.addDevice")}
        </button>
      </div>

      {/* شرح + متطلّبات WinRM */}
      <div className="card mb-6 flex items-start gap-3 text-sm border-info/30 bg-info/5">
        <Info className="w-5 h-5 text-info flex-shrink-0 mt-0.5" />
        <div className="text-fg-muted">{t("pages.winrm.hint")}</div>
      </div>

      {showForm && (
        <div className="card mb-6">
          <h3 className="font-bold mb-3">{t("pages.winrm.newDevice")}</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <input
              className="input"
              dir="ltr"
              aria-label={t("pages.winrm.ipPlaceholder")}
              placeholder={t("pages.winrm.ipPlaceholder")}
              value={form.host}
              onChange={(e) => setForm({ ...form, host: e.target.value })}
            />
            <input
              className="input"
              dir="ltr"
              type="number"
              aria-label={t("pages.winrm.portPlaceholder")}
              placeholder={t("pages.winrm.portPlaceholder")}
              value={form.port}
              onChange={(e) => setForm({ ...form, port: Number(e.target.value) })}
            />
            <input
              className="input"
              dir="ltr"
              aria-label={t("pages.winrm.usernameAdmin")}
              placeholder={t("pages.winrm.usernameAdmin")}
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
            />
            <input
              className="input"
              dir="ltr"
              type="password"
              aria-label={t("pages.remote.password")}
              placeholder={t("pages.remote.password")}
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
            />
            <input
              className="input md:col-span-2"
              aria-label={t("pages.remote.customName")}
              placeholder={t("pages.remote.customName")}
              value={form.custom_name}
              onChange={(e) => setForm({ ...form, custom_name: e.target.value })}
            />
            <label className="md:col-span-2 flex items-center gap-2 text-sm text-fg-muted">
              <input
                type="checkbox"
                checked={form.use_https}
                onChange={(e) => {
                  const https = e.target.checked;
                  // Only auto-adjust the port if it's still a default — never
                  // clobber a custom port the user typed.
                  const port =
                    form.port === 5985 || form.port === 5986
                      ? https
                        ? 5986
                        : 5985
                      : form.port;
                  setForm({ ...form, use_https: https, port, verify_tls: https && form.verify_tls });
                }}
              />
              {t("pages.winrm.useHttps")}
            </label>
            {form.use_https && (
              <label className="md:col-span-2 flex items-center gap-2 text-sm text-fg-muted">
                <input
                  type="checkbox"
                  checked={form.verify_tls}
                  onChange={(e) => setForm({ ...form, verify_tls: e.target.checked })}
                />
                {t("pages.winrm.verifyTls")}
              </label>
            )}
          </div>
          <div className="mt-3 flex items-center gap-3">
            <button
              type="button"
              onClick={() => add.mutate()}
              disabled={add.isPending || !form.host || !form.username}
              className="btn-primary inline-flex items-center gap-2"
            >
              {add.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Server className="w-4 h-4" />}
              {t("pages.remote.connectSave")}
            </button>
            <span className="text-xs text-fg-muted">{t("pages.remote.verifyHint")}</span>
          </div>
          {add.isError && <p className="mt-3 text-sm text-danger">{add.error.message}</p>}
        </div>
      )}

      {hosts.isLoading ? (
        <div className="card text-center py-12">
          <Loader2 className="w-8 h-8 animate-spin mx-auto text-fg-muted" />
        </div>
      ) : list.length === 0 ? (
        <div className="card text-center py-16 text-fg-muted">
          <MonitorSmartphone className="w-12 h-12 text-fg-subtle mx-auto mb-3" />
          {t("pages.winrm.empty")}
        </div>
      ) : (
        <div className="space-y-4">
          {list.map((h) => {
            const c = checks[h.id];
            return (
              <div key={h.id} className="card">
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="min-w-0">
                    <div className="font-bold truncate">{h.display_name}</div>
                    <div className="text-xs text-fg-muted" dir="ltr">
                      {h.os_name || "Windows"} · {h.username}@{h.host}:{h.port}
                      {h.use_https ? " (https)" : ""}
                      {!h.has_winget && " · ⚠ winget?"}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <button
                      type="button"
                      onClick={() => check.mutate(h.id)}
                      disabled={check.isPending && check.variables === h.id}
                      className="btn-secondary text-sm inline-flex items-center gap-2"
                    >
                      {check.isPending && check.variables === h.id ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <RefreshCw className="w-4 h-4" />
                      )}
                      {t("pages.remote.checkUpdates")}
                    </button>
                    {c && c.total > 0 && (
                      <button
                        type="button"
                        onClick={() => {
                          if (
                            window.confirm(
                              t("pages.remote.upgradeConfirm", { count: c.total, name: h.display_name })
                            )
                          )
                            upgrade.mutate(h.id);
                        }}
                        disabled={upgrade.isPending && upgrade.variables === h.id}
                        className="btn-primary text-sm inline-flex items-center gap-2"
                      >
                        {upgrade.isPending && upgrade.variables === h.id ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <Download className="w-4 h-4" />
                        )}
                        {t("pages.remote.upgradeAll", { count: c.total })}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => remove.mutate(h.id)}
                      className="btn-secondary text-sm text-danger"
                      title={t("pages.remote.delete")}
                      aria-label={t("pages.remote.delete")}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {check.isError && check.variables === h.id && (
                  <p className="mt-3 text-sm text-danger">{check.error.message}</p>
                )}
                {upgrade.isError && upgrade.variables === h.id && (
                  <p className="mt-3 text-sm text-danger">
                    {t("pages.winrm.upgradeFailed")} {upgrade.error.message}
                  </p>
                )}
                {remove.isError && remove.variables === h.id && (
                  <p className="mt-3 text-sm text-danger">
                    {t("pages.remote.deleteFailed")} {remove.error.message}
                  </p>
                )}
                {upgradeResults[h.id] && !upgradeResults[h.id].succeeded && (
                  <div className="mt-3 p-3 rounded-md border border-danger/30 bg-danger/10 text-danger text-xs">
                    {t("pages.winrm.upgradeIncomplete")}
                    <pre dir="ltr" className="mt-1 whitespace-pre-wrap font-mono max-h-32 overflow-y-auto">
                      {upgradeResults[h.id].output_tail.slice(-500)}
                    </pre>
                  </div>
                )}
                {c &&
                  (c.total === 0 ? (
                    <p className="mt-3 text-sm text-success inline-flex items-center gap-1">
                      <CheckCircle2 className="w-4 h-4" /> {t("pages.winrm.allUpToDate")}
                    </p>
                  ) : (
                    <div className="mt-3 bg-surface-2 rounded-lg p-3">
                      <div className="text-sm font-medium mb-2">{t("pages.linux.upgradable", { count: c.total })}</div>
                      <ul className="text-xs font-mono divide-y divide-border max-h-48 overflow-y-auto" dir="ltr">
                        {c.packages.slice(0, 50).map((p) => (
                          <li key={p.id} className="py-1 flex justify-between gap-2">
                            <span className="truncate" title={p.id}>
                              {p.name || p.id}
                            </span>
                            <span className="text-fg-muted flex-shrink-0">
                              {p.current} → {p.available}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-6 text-center text-xs text-fg-subtle inline-flex items-center gap-1 w-full justify-center">
        <ShieldCheck className="w-3 h-3" /> {t("pages.winrm.tlsNote")}
      </div>
    </div>
  );
}
