import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  ArrowRight,
  Loader2,
  Terminal,
  Plus,
  Trash2,
  RefreshCw,
  Download,
  CheckCircle2,
  Server,
} from "lucide-react";
import { apiFetch } from "@/lib/utils";
import { useLanguage } from "@/lib/language";

// ================================================================
// صفحة Linux/SSH — تحديثات أجهزة لينكس عبر apt/dnf
// ================================================================

interface SSHHost {
  id: number;
  host: string;
  port: number;
  username: string;
  custom_name: string;
  os_name: string;
  pkg_manager: string;
  is_online: boolean;
  host_key_verified: boolean;
  display_name: string;
}
interface UpdateCheck {
  total: number;
  packages: { name: string; current: string; available: string }[];
}

export function LinuxPage({ onBack }: { onBack: () => void }) {
  const { t } = useTranslation();
  const { dir } = useLanguage();
  const qc = useQueryClient();
  const BackIcon = dir === "rtl" ? ArrowRight : ArrowLeft;

  const hosts = useQuery<{ hosts: SSHHost[]; total: number }>({
    queryKey: ["ssh-hosts"],
    queryFn: () => apiFetch("/api/ssh/hosts"),
  });

  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ host: "", port: 22, username: "", password: "", custom_name: "" });
  const [checks, setChecks] = useState<Record<number, UpdateCheck>>({});

  const add = useMutation({
    mutationFn: () => apiFetch("/api/ssh/hosts", { method: "POST", body: JSON.stringify(form) }),
    onSuccess: () => {
      setShowForm(false);
      setForm({ host: "", port: 22, username: "", password: "", custom_name: "" });
      qc.invalidateQueries({ queryKey: ["ssh-hosts"] });
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => apiFetch(`/api/ssh/hosts/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ssh-hosts"] }),
  });

  const check = useMutation<UpdateCheck, Error, number>({
    mutationFn: (id) => apiFetch<UpdateCheck>(`/api/ssh/hosts/${id}/check`, { method: "POST", body: "{}" }),
    onSuccess: (data, id) => setChecks((c) => ({ ...c, [id]: data })),
  });

  const upgrade = useMutation({
    mutationFn: (id: number) => apiFetch(`/api/ssh/hosts/${id}/upgrade`, { method: "POST", body: "{}" }),
    onSuccess: (_d, id) => check.mutate(id),
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
          <Terminal className="w-5 h-5 text-primary" />
          <h2 className="text-xl font-display font-bold">{t("pages.linux.title")}</h2>
        </div>
        <button type="button" onClick={() => setShowForm((s) => !s)} className="btn-primary inline-flex items-center gap-2">
          <Plus className="w-4 h-4" /> {t("pages.remote.addDevice")}
        </button>
      </div>

      {showForm && (
        <div className="card mb-6">
          <h3 className="font-bold mb-3">{t("pages.linux.newDevice")}</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <input className="input" dir="ltr" placeholder={t("pages.linux.ipPlaceholder")} value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} />
            <input className="input" dir="ltr" type="number" placeholder={t("pages.linux.portPlaceholder")} value={form.port} onChange={(e) => setForm({ ...form, port: Number(e.target.value) })} />
            <input className="input" dir="ltr" placeholder={t("pages.remote.username")} value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
            <input className="input" dir="ltr" type="password" placeholder={t("pages.remote.password")} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            <input className="input md:col-span-2" placeholder={t("pages.remote.customName")} value={form.custom_name} onChange={(e) => setForm({ ...form, custom_name: e.target.value })} />
          </div>
          <div className="mt-3 flex items-center gap-3">
            <button type="button" onClick={() => add.mutate()} disabled={add.isPending || !form.host || !form.username} className="btn-primary inline-flex items-center gap-2">
              {add.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Server className="w-4 h-4" />}
              {t("pages.remote.connectSave")}
            </button>
            <span className="text-xs text-fg-muted">{t("pages.remote.verifyHint")}</span>
          </div>
          {add.isError && <p className="mt-3 text-sm text-danger">{add.error.message}</p>}
        </div>
      )}

      {hosts.isLoading ? (
        <div className="card text-center py-12"><Loader2 className="w-8 h-8 animate-spin mx-auto text-fg-muted" /></div>
      ) : list.length === 0 ? (
        <div className="card text-center py-16 text-fg-muted">
          <Terminal className="w-12 h-12 text-fg-subtle mx-auto mb-3" />
          {t("pages.linux.empty")}
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
                      {h.os_name || "Linux"} · {h.username}@{h.host}:{h.port} · {h.pkg_manager || "?"}
                      {h.host_key_verified && (
                        <span className="text-success" title={t("pages.linux.hostKeyVerified")}>
                          {" "}· 🔒
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <button type="button" onClick={() => check.mutate(h.id)} disabled={check.isPending && check.variables === h.id} className="btn-secondary text-sm inline-flex items-center gap-2">
                      {check.isPending && check.variables === h.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                      {t("pages.remote.checkUpdates")}
                    </button>
                    {c && c.total > 0 && (
                      <button
                        type="button"
                        onClick={() => {
                          if (window.confirm(t("pages.remote.upgradeConfirm", { count: c.total, name: h.display_name }))) upgrade.mutate(h.id);
                        }}
                        disabled={upgrade.isPending && upgrade.variables === h.id}
                        className="btn-primary text-sm inline-flex items-center gap-2"
                      >
                        {upgrade.isPending && upgrade.variables === h.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                        {t("pages.remote.upgradeAll", { count: c.total })}
                      </button>
                    )}
                    <button type="button" onClick={() => remove.mutate(h.id)} className="btn-secondary text-sm text-danger" title={t("pages.remote.delete")}>
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {check.isError && check.variables === h.id && (
                  <p className="mt-3 text-sm text-danger">{check.error.message}</p>
                )}
                {c &&
                  (c.total === 0 ? (
                    <p className="mt-3 text-sm text-success inline-flex items-center gap-1">
                      <CheckCircle2 className="w-4 h-4" /> {t("pages.linux.upToDate")}
                    </p>
                  ) : (
                    <div className="mt-3 bg-surface-2 rounded-lg p-3">
                      <div className="text-sm font-medium mb-2">{t("pages.linux.upgradable", { count: c.total })}</div>
                      <ul className="text-xs font-mono divide-y divide-border max-h-48 overflow-y-auto" dir="ltr">
                        {c.packages.slice(0, 50).map((p) => (
                          <li key={p.name} className="py-1 flex justify-between gap-2">
                            <span className="truncate">{p.name}</span>
                            <span className="text-fg-muted flex-shrink-0">{p.current} → {p.available}</span>
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
    </div>
  );
}
