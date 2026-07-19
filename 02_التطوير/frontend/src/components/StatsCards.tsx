import { useTranslation } from "react-i18next";
import { Network, Wifi, Router, Smartphone, Laptop, Tv, Cpu, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

// ================================================================
// Stats cards — top of the Devices page
// 4 quick-glance cards driven by GET /api/devices/stats
// ================================================================

export interface DeviceStats {
  total: number;
  online: number;
  offline: number;
  by_type: Record<string, number>;
}

export function StatsCards({ stats, isLoading }: { stats?: DeviceStats; isLoading?: boolean }) {
  const { t } = useTranslation();

  const total = stats?.total ?? 0;
  const online = stats?.online ?? 0;
  const byType = stats?.by_type ?? {};

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <StatCard
        label={t("stats.total")}
        value={total}
        icon={Network}
        accent="primary"
        loading={isLoading}
      />
      <StatCard
        label={t("stats.online")}
        value={online}
        icon={Wifi}
        accent="success"
        loading={isLoading}
      />
      <StatCard
        label={t("stats.routers")}
        value={byType.router ?? 0}
        icon={Router}
        accent="info"
        loading={isLoading}
      />
      <StatCard
        label={t("stats.phones")}
        value={byType.phone ?? 0}
        icon={Smartphone}
        accent="accent"
        loading={isLoading}
      />
    </div>
  );
}

const ACCENT: Record<string, { bg: string; text: string; ring: string }> = {
  primary: { bg: "bg-primary/10", text: "text-primary", ring: "ring-primary/20" },
  success: { bg: "bg-success/10", text: "text-success", ring: "ring-success/20" },
  info:    { bg: "bg-info/10",    text: "text-info",    ring: "ring-info/20" },
  accent:  { bg: "bg-accent/10",  text: "text-accent",  ring: "ring-accent/20" },
};

function StatCard({
  label,
  value,
  icon: Icon,
  accent,
  loading,
}: {
  label: string;
  value: number;
  icon: LucideIcon;
  accent: "primary" | "success" | "info" | "accent";
  loading?: boolean;
}) {
  const colors = ACCENT[accent];
  return (
    <div className="card !p-4 flex items-center gap-4 transition-all hover:shadow-lg">
      <div
        className={cn(
          "w-12 h-12 rounded-xl flex items-center justify-center ring-1",
          colors.bg,
          colors.ring
        )}
      >
        <Icon className={cn("w-6 h-6", colors.text)} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-xs text-fg-muted truncate">{label}</div>
        <div className={cn("text-2xl font-display font-bold tabular-nums", colors.text)}>
          {loading ? "—" : value.toLocaleString()}
        </div>
      </div>
    </div>
  );
}

// Optional secondary row for less-prominent stats
export function StatsCardsSecondary({ stats }: { stats?: DeviceStats }) {
  const { t } = useTranslation();
  const byType = stats?.by_type ?? {};
  const items: Array<[string, number, LucideIcon]> = [
    [t("stats.computers"), byType.computer ?? 0, Laptop],
    [t("stats.tvs"), byType.smart_tv ?? 0, Tv],
    [t("stats.iot"), byType.iot ?? 0, Cpu],
  ];
  return (
    <div className="flex items-center gap-4 mb-6 flex-wrap">
      {items.map(([label, value, Icon]) => (
        <div
          key={label}
          className="flex items-center gap-2 px-3 py-1.5 rounded-md border border-border bg-surface text-sm"
        >
          <Icon className="w-4 h-4 text-fg-muted" />
          <span className="text-fg-muted">{label}</span>
          <span className="font-bold tabular-nums">{value.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}
