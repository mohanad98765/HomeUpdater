import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Ban,
  Check,
  ChevronDown,
  Clock,
  Copy,
  Fingerprint,
  KeyRound,
  Loader2,
  Power,
  RefreshCw,
  Server,
  ServerCog,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { apiFetch, cn, type ApiError } from "@/lib/utils";
import { useLanguage } from "@/lib/language";

// ================================================================
// الوكلاء — واجهة المشغّل.
//
// المبدأ الحاكم هنا هو نفسه في بقيّة المنتج: لا وعد بما لا نملكه. وله ثلاثة
// آثار ملموسة في هذه الصفحة تحديدًا:
//
//   • لا زرّ «ثبِّت التحديثات» ولا «رقِّ البرامج»: المركز يستقبل عدد التحديثات
//     لا قائمة معرِّفاتها، والوكيل يرفض أي معرِّف لم يُبلِّغ عنه هو. زرٌّ كهذا
//     مضمون الفشل. ولا «اجرد الآن» لأن الجرد يحدث في كل اتّصال أصلًا.
//   • تأكيد الجهاز يتطلّب كتابة آخر ثماني خانات من البصمة. المركز يُخفيها،
//     وهي مطبوعة على شاشة الجهاز الهدف — فالإجابة إثباتُ وصولٍ إليه. لو عرضناها
//     بجوار الزرّ لصار «قارن ثم أكِّد» نسخًا من الصندوق المجاور.
//   • لافتة الحدود دائمة وغير قابلة للإخفاء: الوكيل يتوقّف عند إعادة التشغيل
//     ولا يُحدِّث نفسه. عميلٌ يدفع يجب أن يعرف هذا قبل أن يعتمد عليه.
// ================================================================

interface ReportedItem {
  kind: string;
  item_id: string;
  title: string;
  current_version: string;
  available_version: string;
  severity: string;
  size_mb: number;
  requires_reboot: boolean;
}
interface ReportedItems {
  updates: ReportedItem[];
  packages: ReportedItem[];
  reported_at: string | null;
  truncated: boolean;
}

/** What one machine reported, and the only things the operator may ask it to install.
 *
 * The list is deliberately the agent's own report rather than anything the hub composed:
 * the agent refuses every id it did not itself report, so offering a choice from any
 * other source would produce commands that are guaranteed to be refused. */
function RemoteUpdates({ agent }: { agent: Agent }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<Record<string, boolean>>({});

  const items = useQuery<ReportedItems>({
    queryKey: ["agent-items", agent.id],
    queryFn: () => apiFetch<ReportedItems>(`/api/agents/${agent.id}/items`),
    enabled: open,
  });

  const send = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiFetch(`/api/agents/${agent.id}/command`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      setPicked({});
      qc.invalidateQueries({ queryKey: ["agent-commands", agent.id] });
    },
  });

  const updates = items.data?.updates ?? [];
  const packages = items.data?.packages ?? [];
  const chosenUpdates = updates.filter((u) => picked[`u:${u.item_id}`]).map((u) => u.item_id);
  const chosenPackages = packages.filter((p) => picked[`p:${p.item_id}`]).map((p) => p.item_id);
  const total = chosenUpdates.length + chosenPackages.length;

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-xs underline text-primary"
      >
        {open ? t("pages.agents.remote.hide") : t("pages.agents.remote.show")}
      </button>

      {open && (
        <div className="mt-2 border border-border rounded-md p-3 space-y-2">
          {items.isLoading && <p className="text-xs text-fg-muted">{t("common.loading")}</p>}
          {items.data && !updates.length && !packages.length && (
            <p className="text-xs text-fg-muted">{t("pages.agents.remote.nothing")}</p>
          )}
          {items.data?.truncated && (
            <p className="text-xs text-warning">{t("pages.agents.remote.truncated")}</p>
          )}

          {[...updates, ...packages].map((it) => {
            const key = `${it.kind === "package" ? "p" : "u"}:${it.item_id}`;
            return (
              <label key={key} className="flex items-start gap-2 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  checked={!!picked[key]}
                  onChange={(e) => setPicked({ ...picked, [key]: e.target.checked })}
                  className="mt-0.5"
                />
                <span className="min-w-0">
                  <span className="block truncate">{it.title || it.item_id}</span>
                  <span className="text-fg-subtle font-mono text-[10px]">
                    {it.kind === "package"
                      ? `${it.current_version} → ${it.available_version}`
                      : [it.severity, it.size_mb ? `${it.size_mb.toFixed(0)} MB` : ""]
                          .filter(Boolean)
                          .join(" · ")}
                  </span>
                </span>
              </label>
            );
          })}

          {total > 0 && (
            <button
              type="button"
              disabled={send.isPending}
              onClick={() => {
                if (chosenUpdates.length) {
                  send.mutate({ kind: "windows_updates_install", update_ids: chosenUpdates });
                }
                if (chosenPackages.length) {
                  send.mutate({ kind: "software_upgrade", product_ids: chosenPackages });
                }
              }}
              className="btn-primary text-xs"
            >
              {t("pages.agents.remote.install", { n: total })}
            </button>
          )}
          {send.isSuccess && (
            <p className="text-xs text-success">{t("pages.agents.remote.queued")}</p>
          )}
          {send.isError && (
            <p className="text-xs text-danger">{(send.error as Error)?.message}</p>
          )}
        </div>
      )}
    </div>
  );
}

interface Agent {
  id: string;
  fingerprint: string | null;
  fingerprint_head: string;
  fingerprint_masked?: string;
  name: string;
  os_name: string;
  agent_version: string;
  status: "pending" | "active" | "revoked";
  enrolled_at: string | null;
  last_seen: string | null;
  last_skew_seconds: number;
  inventory_count: number;
  pending_updates: number;
}
interface AgentList {
  agents: Agent[];
  total: number;
  counts: { pending: number; active: number; revoked: number };
}
interface ListenerStatus {
  enabled: boolean;
  running: boolean;
  host: string;
  port: number;
  error: string;
  certificate: {
    fingerprint_sha256?: string;
    not_before?: string;
    not_after?: string;
    names?: string[];
    self_signed?: boolean;
  };
  addresses: string[];
}
interface Minted {
  token: string;
  expires_at: string;
  bound: boolean;
  requires_confirmation: boolean;
  target_hint: string;
}
interface Refusal {
  at: string;
  agent_id: string;
  agent_name: string | null;
  reason: string;
  path: string;
  source: string;
}

// The agent checks in every 300s. Late is "missed one", silent is "missed several".
const LATE_AFTER = 600;
const SILENT_AFTER = 1800;

function grouped(fp: string): string {
  return (fp.match(/.{1,8}/g) ?? []).join(" ");
}

function secondsSince(iso: string | null): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : Math.max(0, Math.round((Date.now() - t) / 1000));
}

/** Copy that never becomes a dead end: the text stays selectable either way. */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const { t } = useTranslation();
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      aria-label={label}
      onClick={async () => {
        if (await copyText(value)) {
          setDone(true);
          setTimeout(() => setDone(false), 2000);
        }
      }}
      className="btn-secondary inline-flex items-center gap-1 text-xs shrink-0"
    >
      {done ? <Check className="w-3 h-3 text-success" /> : <Copy className="w-3 h-3" />}
      {done ? t("pages.agents.copied") : t("pages.agents.copy")}
    </button>
  );
}

/** A monospace, LTR block inside an RTL page — addresses, commands, fingerprints. */
function Mono({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <code dir="ltr" className={cn("font-mono text-xs break-all select-all", className)}>
      {children}
    </code>
  );
}

export function AgentsPage({ onBack }: { onBack: () => void }) {
  const { t } = useTranslation();
  const { dir } = useLanguage();
  const qc = useQueryClient();
  const BackIcon = dir === "rtl" ? ArrowRight : ArrowLeft;

  // The token lives in component state only: never a query cache, never storage,
  // never a URL. It disappears when the page does.
  const [minted, setMinted] = useState<Minted | null>(null);
  const [hintName, setHintName] = useState("");
  const [boundFp, setBoundFp] = useState("");
  const [useBound, setUseBound] = useState(false);
  const [address, setAddress] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const [confirmOn, setConfirmOn] = useState(false);
  const [confirmOff, setConfirmOff] = useState(false);
  const [suffix, setSuffix] = useState<Record<string, string>>({});
  const [revoking, setRevoking] = useState<string | null>(null);
  const [typedName, setTypedName] = useState("");
  const [showCert, setShowCert] = useState(false);
  const [ackCount, setAckCount] = useState("");
  const [rowError, setRowError] = useState<Record<string, string>>({});
  const mintedAt = useRef<number>(0);

  const listener = useQuery<ListenerStatus>({
    queryKey: ["agent-listener"],
    queryFn: () => apiFetch<ListenerStatus>("/api/agents/listener"),
    refetchInterval: 30_000,
  });
  const running = listener.data?.running ?? false;

  const tokenAlive = minted !== null && Date.parse(minted.expires_at) > now;
  const fleet = useQuery<AgentList>({
    queryKey: ["agents"],
    queryFn: () => apiFetch<AgentList>("/api/agents"),
    // The arrival of a machine is the moment this page exists for; outside that
    // window nothing changes faster than the five-minute check-in.
    refetchInterval: tokenAlive ? 5_000 : 30_000,
  });
  const refusals = useQuery<{ refusals: Refusal[]; total: number }>({
    queryKey: ["agent-refusals"],
    queryFn: () => apiFetch<{ refusals: Refusal[]; total: number }>("/api/agents/refusals"),
    refetchInterval: 30_000,
  });

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const first = listener.data?.addresses?.[0];
    if (first && !address) setAddress(first);
  }, [listener.data, address]);

  const toggle = useMutation<ListenerStatus, ApiError, boolean>({
    mutationFn: (enabled) =>
      apiFetch<ListenerStatus>("/api/agents/listener", {
        method: "POST",
        body: JSON.stringify({ enabled }),
      }),
    onSuccess: (data) => {
      qc.setQueryData(["agent-listener"], data);
      setConfirmOn(false);
      setConfirmOff(false);
    },
  });

  const mint = useMutation<Minted, ApiError, void>({
    mutationFn: () =>
      apiFetch<Minted>("/api/agents/enrolment-token", {
        method: "POST",
        body: JSON.stringify(
          useBound
            ? { target_hint: hintName, machine_fingerprint: boundFp }
            : { target_hint: hintName, allow_any_machine: true },
        ),
      }),
    onSuccess: (data) => {
      mintedAt.current = Date.now();
      setMinted(data);
    },
  });

  const confirmAgent = useMutation<Agent, ApiError, { id: string; value: string }>({
    mutationFn: ({ id, value }) =>
      apiFetch<Agent>(`/api/agents/${id}/confirm`, {
        method: "POST",
        body: JSON.stringify({ fingerprint_suffix: value }),
      }),
    onSuccess: (_d, v) => {
      setSuffix((s) => ({ ...s, [v.id]: "" }));
      setRowError((e) => ({ ...e, [v.id]: "" }));
      qc.invalidateQueries({ queryKey: ["agents"] });
    },
    onError: (err, v) => setRowError((e) => ({ ...e, [v.id]: err.message })),
  });

  const revoke = useMutation<Agent, ApiError, string>({
    mutationFn: (id) => apiFetch<Agent>(`/api/agents/${id}/revoke`, { method: "POST" }),
    onSuccess: () => {
      setRevoking(null);
      setTypedName("");
      qc.invalidateQueries({ queryKey: ["agents"] });
    },
  });

  const forget = useMutation<{ deleted: boolean }, ApiError, string>({
    mutationFn: (id) =>
      apiFetch<{ deleted: boolean }>(`/api/agents/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setRevoking(null);
      setTypedName("");
      qc.invalidateQueries({ queryKey: ["agents"] });
    },
  });

  const regenerate = useMutation<{ warning: string }, ApiError, number>({
    mutationFn: (count) =>
      apiFetch<{ warning: string }>("/api/agents/listener/certificate/regenerate", {
        method: "POST",
        body: JSON.stringify({ acknowledge_agents: count }),
      }),
    onSuccess: () => {
      setAckCount("");
      qc.invalidateQueries({ queryKey: ["agent-listener"] });
    },
  });

  const command = useMemo(() => {
    const hub = address || `https://HOST:${listener.data?.port ?? 8443}`;
    const name = hintName.trim();
    return [
      "HomeUpdater.exe --agent",
      `--hub ${hub}`,
      `--token ${minted?.token ?? ""}`,
      name ? `--name ${name}` : "",
    ]
      .filter(Boolean)
      .join(" ");
  }, [address, hintName, minted, listener.data]);

  const remaining = minted ? Math.max(0, Math.round((Date.parse(minted.expires_at) - now) / 1000)) : 0;
  const clock = `${String(Math.floor(remaining / 60)).padStart(2, "0")}:${String(remaining % 60).padStart(2, "0")}`;

  const agents = fleet.data?.agents ?? [];
  const breakable = agents.filter((a) => a.status !== "revoked").length;
  const anySilent = agents.some(
    (a) => a.status === "active" && (secondsSince(a.last_seen) ?? Infinity) > LATE_AFTER,
  );

  return (
    <div className="max-w-4xl mx-auto px-6 py-8" data-testid="agents-page">
      <div className="flex items-center justify-between gap-3 mb-6">
        <button type="button" onClick={onBack} className="btn-secondary inline-flex items-center gap-2">
          <BackIcon className="w-4 h-4" />
          <span className="hidden sm:inline">{t("nav.dashboard")}</span>
        </button>
        <div className="flex items-center gap-2">
          <ServerCog className="w-5 h-5 text-primary" />
          <div>
            <h2 className="text-xl font-display font-bold leading-tight flex items-center gap-2">
              {t("pages.agents.title")}
              <span className="text-xs px-2 py-0.5 rounded-full border border-warning/40 bg-warning/10 text-warning">
                {t("pages.agents.badge")}
              </span>
            </h2>
            <p className="text-xs text-fg-muted">{t("pages.agents.subtitle")}</p>
          </div>
        </div>
        <div className="w-20" />
      </div>

      {/* الحدود — دائمة، في كل حالة، بلا زرّ إخفاء */}
      <section className="card mb-5 border-warning/40 bg-warning/5">
        <div className="flex items-center gap-2 mb-2">
          <AlertTriangle className="w-4 h-4 text-warning" />
          <h3 className="font-display font-bold">{t("pages.agents.limits.title")}</h3>
        </div>
        <ul className="text-sm text-fg-muted space-y-1 list-disc ms-5">
          <li>{t("pages.agents.limits.reboot")}</li>
          <li>{t("pages.agents.limits.selfUpdate")}</li>
          <li>{t("pages.agents.limits.noCommands")}</li>
        </ul>
      </section>

      {/* ١) الاستقبال */}
      {/* The state is on the element, not inferred from the badge: "Closed" renders
          identically while loading and when the port really is closed, and every
          control on this page is disabled until the real state is known. */}
      <section className="card mb-5" data-testid={listener.isLoading ? "listener-loading" : "listener-ready"}>
        <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
          <div className="flex items-center gap-2">
            <Server className="w-4 h-4 text-primary" />
            <h3 className="font-display font-bold">{t("pages.agents.listener.title")}</h3>
            <span
              className={cn(
                "badge",
                running
                  ? "badge-success"
                  : listener.data?.enabled
                    ? "badge-danger"
                    : "badge-info",
              )}
            >
              {running
                ? t("pages.agents.listener.stateRunning", { port: listener.data?.port })
                : listener.data?.enabled
                  ? t("pages.agents.listener.stateBroken")
                  : t("pages.agents.listener.stateOff")}
            </span>
          </div>
          {!confirmOn && !confirmOff && (
            <button
              type="button"
              onClick={() => (running ? setConfirmOff(true) : setConfirmOn(true))}
              disabled={toggle.isPending || listener.isLoading}
              className={cn("inline-flex items-center gap-2", running ? "btn-secondary" : "btn-primary")}
            >
              {toggle.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Power className="w-4 h-4" />
              )}
              {running ? t("pages.agents.listener.close") : t("pages.agents.listener.open")}
            </button>
          )}
        </div>

        <p className="text-sm text-fg-muted mb-3">{t("pages.agents.listener.hint")}</p>

        {confirmOn && (
          <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 mb-3">
            <p className="text-sm mb-2">
              {t("pages.agents.listener.confirmOpen", { port: listener.data?.port ?? 8443 })}
            </p>
            <div className="flex gap-2">
              <button type="button" onClick={() => toggle.mutate(true)} className="btn-primary text-sm">
                {t("pages.agents.listener.open")}
              </button>
              <button type="button" onClick={() => setConfirmOn(false)} className="btn-secondary text-sm">
                {t("common.cancel")}
              </button>
            </div>
          </div>
        )}
        {confirmOff && (
          <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 mb-3">
            <p className="text-sm mb-2">{t("pages.agents.listener.confirmClose")}</p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => toggle.mutate(false)}
                className="btn-secondary text-danger text-sm"
              >
                {t("pages.agents.listener.close")}
              </button>
              <button type="button" onClick={() => setConfirmOff(false)} className="btn-secondary text-sm">
                {t("common.cancel")}
              </button>
            </div>
          </div>
        )}

        {listener.data?.enabled && !running && (
          <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 mb-3">
            <p className="text-sm text-danger mb-1">
              {t("pages.agents.listener.startFailed", { port: listener.data.port })}
            </p>
            {listener.data.error && <Mono>{listener.data.error}</Mono>}
            <p className="text-xs text-fg-muted mt-1">{t("pages.agents.listener.brokenHint")}</p>
          </div>
        )}

        {running && (
          <>
            <div className="mb-3">
              <p className="text-xs text-fg-muted mb-1">{t("pages.agents.listener.addressLabel")}</p>
              {(listener.data?.addresses ?? []).length > 1 ? (
                <select
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  aria-label={t("pages.agents.listener.addressLabel")}
                  className="input font-mono text-xs"
                  dir="ltr"
                >
                  {listener.data?.addresses.map((a) => (
                    <option key={a} value={a}>
                      {a}
                    </option>
                  ))}
                </select>
              ) : (
                <Mono>{listener.data?.addresses?.[0] ?? `https://HOST:${listener.data?.port}`}</Mono>
              )}
              <p className="text-xs text-fg-subtle mt-1">{t("pages.agents.listener.addressPick")}</p>
            </div>

            <details className="rounded-lg border border-border p-3">
              <summary className="text-sm cursor-pointer">
                {t("pages.agents.listener.firewallTitle")}
              </summary>
              <p className="text-sm text-fg-muted mt-2 mb-2">
                {t("pages.agents.listener.firewallBody")}
              </p>
              <div className="flex items-start gap-2 flex-wrap">
                <Mono className="flex-1 min-w-[240px]">
                  {`netsh advfirewall firewall add rule name="HomeUpdater Agents" dir=in action=allow protocol=TCP localport=${listener.data?.port ?? 8443}`}
                </Mono>
                <CopyButton
                  value={`netsh advfirewall firewall add rule name="HomeUpdater Agents" dir=in action=allow protocol=TCP localport=${listener.data?.port ?? 8443}`}
                  label={t("pages.agents.copy")}
                />
              </div>
              <p className="text-xs text-fg-subtle mt-2">{t("pages.agents.listener.firewallWhy")}</p>
            </details>
          </>
        )}
      </section>

      {/* ٢) تسجيل جهاز */}
      <section className="card mb-5">
        <div className="flex items-center gap-2 mb-3">
          <KeyRound className="w-4 h-4 text-primary" />
          <h3 className="font-display font-bold">{t("pages.agents.enrol.title")}</h3>
        </div>
        <p className="text-sm text-fg-muted mb-3">{t("pages.agents.enrol.hint")}</p>

        {!running && (
          <p className="text-sm text-warning mb-3">{t("pages.agents.enrol.needListener")}</p>
        )}

        {!minted && (
          <div className="space-y-3">
            <div>
              <label className="text-xs text-fg-muted block mb-1" htmlFor="agent-name">
                {t("pages.agents.enrol.nameLabel")}
              </label>
              <input
                id="agent-name"
                type="text"
                dir="ltr"
                value={hintName}
                onChange={(e) => setHintName(e.target.value)}
                maxLength={80}
                placeholder="PC-Accounting"
                className="input font-mono text-xs w-full sm:w-72"
              />
              <p className="text-xs text-fg-subtle mt-1">{t("pages.agents.enrol.nameHint")}</p>
            </div>

            <label className="flex items-start gap-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={useBound}
                onChange={(e) => setUseBound(e.target.checked)}
                className="mt-1"
              />
              <span>
                {t("pages.agents.enrol.boundLabel")}
                <span className="block text-xs text-fg-subtle">
                  {t("pages.agents.enrol.boundHint")}
                </span>
              </span>
            </label>

            {useBound && (
              <div>
                <input
                  type="text"
                  dir="ltr"
                  value={boundFp}
                  onChange={(e) => setBoundFp(e.target.value)}
                  placeholder="a3f19c02 b7d4e610 8c5f21ab 9034d71e"
                  aria-label={t("pages.agents.enrol.boundLabel")}
                  className="input font-mono text-xs w-full"
                />
                <p className="text-xs text-fg-subtle mt-1">{t("pages.agents.enrol.boundWhere")}</p>
              </div>
            )}

            <p className="text-xs text-warning">
              {useBound ? t("pages.agents.enrol.warnBound") : t("pages.agents.enrol.warnUnbound")}
            </p>

            <button
              type="button"
              onClick={() => mint.mutate()}
              disabled={!running || mint.isPending || (useBound && boundFp.replace(/[\s-]/g, "").length !== 32)}
              className="btn-primary inline-flex items-center gap-2"
            >
              {mint.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <KeyRound className="w-4 h-4" />
              )}
              {t("pages.agents.enrol.create")}
            </button>
            {mint.isError && (
              <p className="text-sm text-danger">
                {t(`pages.agents.enrol.error.${mint.error.message}`, {
                  defaultValue: `${t("pages.agents.enrol.failed")} ${mint.error.message}`,
                })}
              </p>
            )}
          </div>
        )}

        {minted && tokenAlive && (
          <div className="space-y-3">
            <p className="text-sm">{t("pages.agents.enrol.step1")}</p>
            <p className="text-sm">{t("pages.agents.enrol.step2")}</p>
            <div className="flex items-start gap-2 flex-wrap rounded-lg border border-border bg-surface-2 p-3">
              <Mono className="flex-1 min-w-[240px]">{command}</Mono>
              <CopyButton value={command} label={t("pages.agents.copy")} />
            </div>
            <p className="text-sm">
              {minted.requires_confirmation
                ? t("pages.agents.enrol.step3")
                : t("pages.agents.enrol.step3Bound")}
            </p>
            <p
              className={cn(
                "text-sm inline-flex items-center gap-1",
                remaining <= 60 ? "text-danger" : "text-fg-muted",
              )}
            >
              <Clock className="w-4 h-4" />
              {t("pages.agents.enrol.expiresIn", { clock })}
            </p>
            <p className="text-xs text-warning">{t("pages.agents.enrol.warnOnce")}</p>
            <button type="button" onClick={() => setMinted(null)} className="btn-secondary text-sm">
              {t("pages.agents.enrol.done")}
            </button>
          </div>
        )}

        {minted && !tokenAlive && (
          <div className="space-y-2">
            {/* The dead command is removed, not greyed: a pasted expired token is a
                support call that reads as "your product is broken". */}
            <p className="text-sm text-danger">{t("pages.agents.enrol.expired")}</p>
            <button type="button" onClick={() => setMinted(null)} className="btn-primary text-sm">
              {t("pages.agents.enrol.createAnother")}
            </button>
          </div>
        )}
      </section>

      {/* ٣) الأجهزة */}
      <section className="card mb-5">
        <div className="flex items-center gap-2 mb-3">
          <Fingerprint className="w-4 h-4 text-primary" />
          <h3 className="font-display font-bold">{t("pages.agents.fleet.title")}</h3>
        </div>

        {fleet.isLoading && (
          <p className="text-sm text-fg-muted inline-flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" /> {t("status.loading")}
          </p>
        )}

        {fleet.isError && (
          <div>
            <p className="text-sm text-danger mb-2">{t("pages.agents.fleet.loadFailed")}</p>
            <button type="button" onClick={() => fleet.refetch()} className="btn-secondary text-sm">
              {t("pages.agents.retry")}
            </button>
          </div>
        )}

        {fleet.isSuccess && agents.length === 0 && (
          <div className="text-sm text-fg-muted">
            <p>{t("pages.agents.fleet.empty")}</p>
            <p className="text-xs text-fg-subtle mt-1">{t("pages.agents.fleet.emptyHint")}</p>
          </div>
        )}

        <div className="space-y-3">
          {agents.map((a) => {
            const age = secondsSince(a.last_seen);
            const health =
              a.status !== "active"
                ? null
                : age === null
                  ? "never"
                  : age > SILENT_AFTER
                    ? "silent"
                    : age > LATE_AFTER
                      ? "late"
                      : "ok";
            return (
              <div
                key={a.id}
                className={cn(
                  "rounded-lg border p-3",
                  a.status === "pending"
                    ? "border-warning/50 bg-warning/5"
                    : a.status === "revoked"
                      ? "border-border opacity-60"
                      : "border-border",
                )}
              >
                <div className="flex items-center justify-between gap-2 flex-wrap mb-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-bold">{a.name || a.fingerprint_head}</span>
                    <span
                      className={cn(
                        "badge",
                        a.status === "active"
                          ? health === "ok"
                            ? "badge-success"
                            : health === "late"
                              ? "badge-warning"
                              : "badge-danger"
                          : a.status === "pending"
                            ? "badge-warning"
                            : "badge-info",
                      )}
                    >
                      {a.status === "pending"
                        ? t("pages.agents.fleet.statusPending")
                        : a.status === "revoked"
                          ? t("pages.agents.fleet.statusRevoked")
                          : t(`pages.agents.fleet.health.${health}`)}
                    </span>
                    {a.os_name && <span className="text-xs text-fg-subtle">{a.os_name}</span>}
                    {a.agent_version && (
                      <span className="text-xs text-fg-subtle">v{a.agent_version}</span>
                    )}
                  </div>
                  {a.status !== "revoked" && revoking !== a.id && (
                    <button
                      type="button"
                      onClick={() => {
                        setRevoking(a.id);
                        setTypedName("");
                      }}
                      className="btn-secondary text-danger text-xs inline-flex items-center gap-1"
                    >
                      <Ban className="w-3 h-3" />
                      {t("pages.agents.fleet.revokeBtn")}
                    </button>
                  )}
                  {a.status === "revoked" && revoking !== a.id && (
                    <button
                      type="button"
                      onClick={() => {
                        setRevoking(a.id);
                        setTypedName("");
                      }}
                      className="btn-secondary text-xs inline-flex items-center gap-1"
                    >
                      <Trash2 className="w-3 h-3" />
                      {t("pages.agents.fleet.forgetBtn")}
                    </button>
                  )}
                </div>

                {a.status === "active" && (
                  <div className="text-xs text-fg-muted space-y-0.5 mb-2">
                    <p>
                      {t("pages.agents.fleet.software", { n: a.inventory_count })} ·{" "}
                      {t("pages.agents.fleet.pendingUpdates", { n: a.pending_updates })}
                    </p>
                    {health !== "ok" && (
                      <p className="text-warning">{t(`pages.agents.fleet.hint.${health}`)}</p>
                    )}
                    {Math.abs(a.last_skew_seconds) > 30 && (
                      <p className="text-warning">
                        {t("pages.agents.fleet.skew", { n: Math.round(a.last_skew_seconds) })}
                      </p>
                    )}
                    {a.fingerprint && (
                      <Mono className="text-fg-subtle">{grouped(a.fingerprint)}</Mono>
                    )}
                    <RemoteUpdates agent={a} />
                  </div>
                )}

                {a.status === "pending" && (
                  <div className="space-y-2">
                    <p className="text-sm">{t("pages.agents.fleet.matchBody")}</p>
                    <Mono className="text-base tracking-wider">
                      {a.fingerprint_masked ?? a.fingerprint_head}
                    </Mono>
                    <div className="flex items-end gap-2 flex-wrap">
                      <div>
                        <label
                          className="text-xs text-fg-muted block mb-1"
                          htmlFor={`suffix-${a.id}`}
                        >
                          {t("pages.agents.fleet.suffixLabel")}
                        </label>
                        <input
                          id={`suffix-${a.id}`}
                          type="text"
                          dir="ltr"
                          value={suffix[a.id] ?? ""}
                          onChange={(e) => setSuffix((s) => ({ ...s, [a.id]: e.target.value }))}
                          maxLength={8}
                          placeholder="9034d71e"
                          className="input font-mono text-sm w-40"
                        />
                      </div>
                      <button
                        type="button"
                        onClick={() =>
                          confirmAgent.mutate({ id: a.id, value: (suffix[a.id] ?? "").trim() })
                        }
                        disabled={
                          confirmAgent.isPending || (suffix[a.id] ?? "").trim().length !== 8
                        }
                        className="btn-primary text-sm inline-flex items-center gap-1"
                      >
                        <ShieldCheck className="w-4 h-4" />
                        {t("pages.agents.fleet.confirmBtn")}
                      </button>
                    </div>
                    {rowError[a.id] && (
                      <p className="text-sm text-danger">
                        {t(`pages.agents.fleet.error.${rowError[a.id]}`, {
                          defaultValue: rowError[a.id],
                        })}
                      </p>
                    )}
                  </div>
                )}

                {revoking === a.id && (
                  <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 mt-2">
                    <p className="text-sm mb-2">
                      {a.status === "revoked"
                        ? t("pages.agents.fleet.forgetWarn")
                        : t("pages.agents.fleet.revokeWarn")}
                    </p>
                    <label className="text-xs text-fg-muted block mb-1" htmlFor={`typed-${a.id}`}>
                      {t("pages.agents.fleet.typeName", {
                        name: a.name || a.fingerprint_head,
                      })}
                    </label>
                    <input
                      id={`typed-${a.id}`}
                      type="text"
                      dir="ltr"
                      value={typedName}
                      onChange={(e) => setTypedName(e.target.value)}
                      className="input font-mono text-xs w-full sm:w-72 mb-2"
                    />
                    <div className="flex gap-2">
                      <button
                        type="button"
                        disabled={typedName.trim() !== (a.name || a.fingerprint_head)}
                        onClick={() =>
                          a.status === "revoked" ? forget.mutate(a.id) : revoke.mutate(a.id)
                        }
                        className="btn-secondary text-danger text-sm"
                      >
                        {a.status === "revoked"
                          ? t("pages.agents.fleet.forgetBtn")
                          : t("pages.agents.fleet.revokeBtn")}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setRevoking(null);
                          setTypedName("");
                        }}
                        className="btn-secondary text-sm"
                      >
                        {t("common.cancel")}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {agents.some((a) => a.status === "active") && (
          <p className="text-xs text-fg-subtle mt-3">{t("pages.agents.fleet.noRemoteInstall")}</p>
        )}
      </section>

      {/* ٤) الطلبات المرفوضة */}
      <section className="card mb-5">
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle className="w-4 h-4 text-primary" />
          <h3 className="font-display font-bold">{t("pages.agents.refusals.title")}</h3>
        </div>
        <p className="text-sm text-fg-muted mb-3">{t("pages.agents.refusals.intro")}</p>

        {(refusals.data?.refusals ?? []).length === 0 ? (
          <div className="text-sm text-fg-muted">
            <p>{t("pages.agents.refusals.empty")}</p>
            {anySilent && (
              <p className="text-warning mt-2">{t("pages.agents.refusals.emptyButSilent")}</p>
            )}
          </div>
        ) : (
          <ul className="space-y-2">
            {refusals.data?.refusals.map((r, i) => (
              <li key={`${r.at}-${i}`} className="text-sm border-b border-border pb-2 last:border-0">
                <div className="flex items-center gap-2 flex-wrap text-xs text-fg-subtle">
                  <span>{new Date(r.at).toLocaleTimeString()}</span>
                  {r.source && <Mono>{r.source}</Mono>}
                  {r.agent_name && <span>{r.agent_name}</span>}
                </div>
                <p>
                  {t(`pages.agents.refusals.reason.${r.reason.split(":")[0]}`, {
                    n: r.reason.split(":")[1] ?? "",
                    defaultValue: r.reason,
                  })}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ٥) الشهادة */}
      <section className="card">
        <button
          type="button"
          onClick={() => setShowCert((v) => !v)}
          className="flex items-center gap-2 w-full text-start"
        >
          <ChevronDown className={cn("w-4 h-4 transition-transform", showCert && "rotate-180")} />
          <h3 className="font-display font-bold">{t("pages.agents.cert.title")}</h3>
        </button>

        {showCert && (
          <div className="mt-3 space-y-3">
            <p className="text-sm text-fg-muted">{t("pages.agents.cert.selfSigned")}</p>
            {listener.data?.certificate?.fingerprint_sha256 ? (
              <>
                <div>
                  <p className="text-xs text-fg-muted mb-1">{t("pages.agents.cert.pinLabel")}</p>
                  <Mono>{listener.data.certificate.fingerprint_sha256}</Mono>
                </div>
                {listener.data.certificate.not_after && (
                  <p className="text-xs text-fg-subtle">
                    {t("pages.agents.cert.expires", {
                      date: listener.data.certificate.not_after.slice(0, 10),
                    })}
                  </p>
                )}
                <div className="rounded-lg border border-danger/40 bg-danger/10 p-3">
                  <p className="text-sm mb-2">
                    {t("pages.agents.cert.regenWarn", { n: breakable })}
                  </p>
                  <input
                    type="text"
                    dir="ltr"
                    value={ackCount}
                    onChange={(e) => setAckCount(e.target.value)}
                    aria-label={t("pages.agents.cert.ackLabel")}
                    placeholder={String(breakable)}
                    className="input font-mono text-xs w-24 mb-2"
                  />
                  <div>
                    <button
                      type="button"
                      disabled={ackCount.trim() !== String(breakable) || regenerate.isPending}
                      onClick={() => regenerate.mutate(breakable)}
                      className="btn-secondary text-danger text-sm inline-flex items-center gap-1"
                    >
                      <RefreshCw className="w-3 h-3" />
                      {t("pages.agents.cert.regenerate")}
                    </button>
                  </div>
                  {regenerate.isSuccess && (
                    <p className="text-sm text-warning mt-2">{t("pages.agents.cert.regenerated")}</p>
                  )}
                  {regenerate.isError && (
                    <p className="text-sm text-danger mt-2">{regenerate.error.message}</p>
                  )}
                </div>
              </>
            ) : (
              <p className="text-sm text-fg-subtle">{t("pages.agents.cert.none")}</p>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
