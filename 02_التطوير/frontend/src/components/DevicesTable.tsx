import { useTranslation } from "react-i18next";
import {
  Router,
  Smartphone,
  Monitor,
  Tv,
  Cpu,
  HelpCircle,
  Circle,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ================================================================
// جدول الأجهزة — يَعرض النتائج المُستلَمة من /api/devices
// ================================================================

export type DeviceType = "router" | "phone" | "computer" | "smart_tv" | "iot" | "unknown";

export interface Device {
  ip: string;
  mac: string;
  hostname: string;
  vendor: string;
  device_type: DeviceType;
  status: "online" | "offline";
  first_seen: string;
  last_seen: string;
}

const ICONS: Record<DeviceType, typeof Cpu> = {
  router:   Router,
  phone:    Smartphone,
  computer: Monitor,
  smart_tv: Tv,
  iot:      Cpu,
  unknown:  HelpCircle,
};

interface Props {
  devices: Device[];
  isScanning?: boolean;
}

export function DevicesTable({ devices, isScanning }: Props) {
  const { t } = useTranslation();

  if (devices.length === 0 && !isScanning) {
    return (
      <div className="text-center py-12 text-fg-muted">
        <Cpu className="w-12 h-12 mx-auto mb-3 text-fg-subtle" />
        <p className="font-medium">{t("devices.empty")}</p>
        <p className="text-xs mt-1">{t("devices.emptyHint")}</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto -mx-6">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-surface-2">
            <th className="text-start font-medium text-fg-muted px-4 py-2">{t("devices.col.type")}</th>
            <th className="text-start font-medium text-fg-muted px-4 py-2">{t("devices.col.host")}</th>
            <th className="text-start font-medium text-fg-muted px-4 py-2 font-mono">{t("devices.col.ip")}</th>
            <th className="text-start font-medium text-fg-muted px-4 py-2 font-mono hidden md:table-cell">{t("devices.col.mac")}</th>
            <th className="text-start font-medium text-fg-muted px-4 py-2 hidden lg:table-cell">{t("devices.col.vendor")}</th>
            <th className="text-start font-medium text-fg-muted px-4 py-2">{t("devices.col.status")}</th>
          </tr>
        </thead>
        <tbody>
          {devices.map((d) => (
            <DeviceRow key={d.mac || d.ip} device={d} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DeviceRow({ device }: { device: Device }) {
  const { t } = useTranslation();
  const Icon = ICONS[device.device_type] ?? HelpCircle;
  const isOnline = device.status === "online";

  return (
    <tr className="border-b border-border hover:bg-surface-2 transition-colors">
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <div
            className={cn(
              "w-8 h-8 rounded-md flex items-center justify-center flex-shrink-0",
              isOnline ? "bg-primary-soft text-primary" : "bg-surface-2 text-fg-subtle"
            )}
          >
            <Icon className="w-4 h-4" />
          </div>
          <span className="text-xs text-fg-muted hidden sm:inline">
            {t(`devices.type.${device.device_type}` as never)}
          </span>
        </div>
      </td>
      <td className="px-4 py-3">
        <div className="font-medium truncate max-w-[200px]">
          {device.hostname || (
            <span className="text-fg-subtle italic">{t("devices.unknownHost")}</span>
          )}
        </div>
      </td>
      <td className="px-4 py-3 font-mono text-xs">{device.ip}</td>
      <td className="px-4 py-3 font-mono text-xs text-fg-muted hidden md:table-cell">
        {device.mac || "—"}
      </td>
      <td className="px-4 py-3 text-xs text-fg-muted truncate max-w-[200px] hidden lg:table-cell">
        {device.vendor || "—"}
      </td>
      <td className="px-4 py-3">
        <span
          className={cn(
            "badge inline-flex items-center gap-1.5",
            isOnline ? "badge-success" : "badge-warning"
          )}
        >
          <Circle
            className={cn("w-2 h-2 fill-current", isOnline ? "animate-pulse" : "opacity-50")}
          />
          {isOnline ? t("status.online") : t("status.offline")}
        </span>
      </td>
    </tr>
  );
}
