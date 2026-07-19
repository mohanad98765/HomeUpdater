import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  ArrowRight,
  Loader2,
  House,
  CheckCircle2,
  AlertTriangle,
  Download,
  Link2,
  RefreshCw,
} from "lucide-react";
import { apiFetch, cn } from "@/lib/utils";
import { useLanguage } from "@/lib/language";

// ================================================================
// صفحة Home Assistant — تحديثات أجهزة المنزل الذكية عبر HA
// ================================================================

interface HAStatus {
  configured: boolean;
  enabled: boolean;
  connected: boolean;
  base_url?: string;
  has_token?: boolean;
  version?: string;
  location_name?: string;
  error?: string;
}
interface HAUpdate {
  entity_id: string;
  title: string;
  installed_version: string | null;
  latest_version: string | null;
  update_available: boolean;
  release_url: string | null;
}
interface HAUpdates {
  total: number;
  available: HAUpdate[];
  up_to_date: number;
}

export function HomeAssistantPage({ onBack }: { onBack: () => void }) {
  const { t } = useTranslation();
  const { dir } = useLanguage();
  const qc = useQueryClient();
  const BackIcon = dir === "rtl" ? ArrowRight : ArrowLeft;

  const status = useQuery<HAStatus>({
    queryKey: ["ha-status"],
    queryFn: () => apiFetch<HAStatus>("/api/homeassistant/status"),
  });

  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  useEffect(() => {
    if (status.data?.base_url) setUrl(status.data.base_url);
  }, [status.data?.base_url]);

  const save = useMutation({
    mutationFn: () =>
      apiFetch("/api/homeassistant/config", {
        method: "POST",
        body: JSON.stringify({ base_url: url, token, enabled: true }),
      }),
    onSuccess: () => {
      setToken("");
      qc.invalidateQueries({ queryKey: ["ha-status"] });
      qc.invalidateQueries({ queryKey: ["ha-updates"] });
    },
  });

  const connected = !!status.data?.connected;

  const updates = useQuery<HAUpdates>({
    queryKey: ["ha-updates"],
    queryFn: () => apiFetch<HAUpdates>("/api/homeassistant/updates"),
    enabled: connected,
  });

  const install = useMutation({
    mutationFn: (entity_id: string) =>
      apiFetch("/api/homeassistant/updates/install", {
        method: "POST",
        body: JSON.stringify({ entity_id }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ha-updates"] }),
  });

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <button type="button" onClick={onBack} className="btn-secondary inline-flex items-center gap-2">
          <BackIcon className="w-4 h-4" />
          <span className="hidden sm:inline">{t("nav.dashboard")}</span>
        </button>
        <div className="flex items-center gap-2">
          <House className="w-5 h-5 text-primary" />
          <h2 className="text-xl font-display font-bold">Home Assistant</h2>
        </div>
        <div className="w-20" />
      </div>

      {/* Connection card */}
      <div className="card mb-6">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <h3 className="font-bold">الاتصال</h3>
          {status.data &&
            (connected ? (
              <span className="badge badge-success inline-flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" />
                متصل {status.data.version && `· ${status.data.version}`}
                {status.data.location_name && ` · ${status.data.location_name}`}
              </span>
            ) : status.data.configured ? (
              <span className="badge badge-danger inline-flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" /> غير متصل
              </span>
            ) : (
              <span className="badge">غير مُهيّأ</span>
            ))}
        </div>

        <label className="block text-sm text-fg-muted mb-1">عنوان Home Assistant</label>
        <input
          type="text"
          dir="ltr"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="http://homeassistant.local:8123"
          className="input w-full mb-3"
        />
        <label className="block text-sm text-fg-muted mb-1">
          رمز الوصول طويل الأمد (Long-Lived Access Token)
        </label>
        <input
          type="password"
          dir="ltr"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder={status.data?.has_token ? "••••••••  (محفوظ — اترك فارغاً للإبقاء عليه)" : "الصق الرمز هنا"}
          className="input w-full mb-3"
        />

        <div className="flex items-center gap-3 flex-wrap">
          <button
            type="button"
            onClick={() => save.mutate()}
            disabled={save.isPending || !url || (!token && !status.data?.has_token)}
            className="btn-primary inline-flex items-center gap-2"
          >
            {save.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Link2 className="w-4 h-4" />}
            حفظ واتصال
          </button>
          <a
            href="https://www.home-assistant.io/docs/authentication/#your-account-profile"
            target="_blank"
            rel="noreferrer noopener"
            className="text-xs text-primary hover:underline"
          >
            كيف أحصل على الرمز؟
          </a>
        </div>

        {save.isError && (
          <p className="mt-3 text-sm text-danger">
            {save.error instanceof Error ? save.error.message : "تعذّر الاتصال"}
          </p>
        )}
        {status.data?.error && !save.isPending && (
          <p className="mt-3 text-sm text-danger">{status.data.error}</p>
        )}
      </div>

      {/* Updates */}
      {connected && (
        <div className="card !p-0 overflow-hidden">
          <div className="flex items-center justify-between p-4 border-b border-border flex-wrap gap-2">
            <h3 className="font-bold">
              تحديثات أجهزة المنزل{" "}
              {updates.data && (
                <span className="text-fg-muted font-normal text-sm">
                  ({updates.data.available.length} متاح · {updates.data.up_to_date} محدَّث)
                </span>
              )}
            </h3>
            <button
              type="button"
              onClick={() => updates.refetch()}
              className="btn-secondary text-sm inline-flex items-center gap-2"
            >
              <RefreshCw className={cn("w-4 h-4", updates.isFetching && "animate-spin")} />
              تحديث
            </button>
          </div>

          {updates.isLoading ? (
            <div className="p-8 text-center">
              <Loader2 className="w-6 h-6 animate-spin mx-auto text-fg-muted" />
            </div>
          ) : (updates.data?.available.length ?? 0) === 0 ? (
            <div className="p-8 text-center text-success">
              <CheckCircle2 className="w-10 h-10 mx-auto mb-2" />
              كل أجهزة Home Assistant محدَّثة ✓
            </div>
          ) : (
            <ul className="divide-y divide-border">
              {updates.data!.available.map((u) => (
                <li key={u.entity_id} className="p-4 flex items-center justify-between gap-4 flex-wrap">
                  <div className="min-w-0">
                    <div className="font-medium truncate">{u.title}</div>
                    <div className="text-xs text-fg-muted font-mono" dir="ltr">
                      {u.installed_version} → {u.latest_version}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => install.mutate(u.entity_id)}
                    disabled={install.isPending}
                    className="btn-primary text-sm inline-flex items-center gap-2"
                  >
                    {install.isPending && install.variables === u.entity_id ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Download className="w-4 h-4" />
                    )}
                    تحديث
                  </button>
                </li>
              ))}
            </ul>
          )}
          {updates.isError && (
            <p className="p-4 text-sm text-danger">
              {updates.error instanceof Error ? updates.error.message : "تعذّر جلب التحديثات"}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
