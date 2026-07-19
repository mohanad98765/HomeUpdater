import {
  Router,
  Smartphone,
  Laptop,
  Tv,
  Cpu,
  HelpCircle,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

export type DeviceType = "router" | "phone" | "computer" | "smart_tv" | "iot" | "unknown";

const ICONS: Record<DeviceType, LucideIcon> = {
  router:    Router,
  phone:     Smartphone,
  computer:  Laptop,
  smart_tv:  Tv,
  iot:       Cpu,
  unknown:   HelpCircle,
};

const TONES: Record<DeviceType, string> = {
  router:    "bg-primary/15 text-primary",
  phone:     "bg-success/15 text-success",
  computer:  "bg-info/15 text-info",
  smart_tv:  "bg-accent/15 text-accent",
  iot:       "bg-warning/15 text-warning",
  unknown:   "bg-fg-muted/15 text-fg-muted",
};

export function DeviceTypeIcon({
  type,
  size = 5,
  className,
}: {
  type: DeviceType;
  /** Tailwind size unit (default 5 = 20px) */
  size?: 4 | 5 | 6 | 8;
  className?: string;
}) {
  const Icon = ICONS[type] ?? HelpCircle;
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded-md",
        TONES[type],
        size === 4 && "w-7 h-7",
        size === 5 && "w-8 h-8",
        size === 6 && "w-10 h-10",
        size === 8 && "w-12 h-12",
        className
      )}
    >
      <Icon className={cn(size === 4 && "w-3.5 h-3.5", size === 5 && "w-4 h-4", size === 6 && "w-5 h-5", size === 8 && "w-6 h-6")} />
    </span>
  );
}
