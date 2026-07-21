import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { X, Save, Loader2, CheckCircle2 } from "lucide-react";
import { apiFetch, cn, formatDateAr } from "@/lib/utils";
import { DeviceTypeIcon, type DeviceType } from "@/components/DeviceTypeIcon";

// ================================================================
// Slide-in panel for editing one device.
// Closes when user clicks the backdrop or the X button.
// ================================================================

export interface Device {
  id: number;
  ip: string;
  mac: string;
  hostname: string;
  vendor: string;
  device_type: DeviceType;
  status: "online" | "offline";
  custom_name: string;
  notes: string;
  display_name: string;
  first_seen: string | null;
  last_seen: string | null;
  // T15 — false for routers/TVs/IoT/unknown that HomeUpdater can't update directly.
  manageable?: boolean;
}

export function DeviceDetailPanel({
  device,
  onClose,
}: {
  device: Device | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [customName, setCustomName] = useState("");
  const [notes, setNotes] = useState("");
  const [savedFlash, setSavedFlash] = useState(false);

  // Reset fields whenever the selected device changes
  useEffect(() => {
    setCustomName(device?.custom_name ?? "");
    setNotes(device?.notes ?? "");
    setSavedFlash(false);
  }, [device?.id]);

  // Close on Escape
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    if (device) document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [device, onClose]);

  const save = useMutation<Device>({
    mutationFn: () =>
      apiFetch<Device>(`/api/devices/${device!.id}`, {
        method: "PATCH",
        body: JSON.stringify({ custom_name: customName, notes }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      qc.invalidateQueries({ queryKey: ["device-stats"] });
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 2000);
    },
  });

  const open = !!device;
  const dirty =
    !!device &&
    (customName !== (device.custom_name ?? "") || notes !== (device.notes ?? ""));

  return (
    <>
      {/* Backdrop */}
      <div
        className={cn(
          "fixed inset-0 bg-black/40 z-40 transition-opacity",
          open ? "opacity-100" : "opacity-0 pointer-events-none"
        )}
        onClick={onClose}
      />

      {/* Drawer */}
      <aside
        className={cn(
          "fixed top-0 bottom-0 end-0 w-full sm:w-[440px] bg-surface text-fg shadow-2xl z-50",
          "border-s border-border flex flex-col",
          "transform transition-transform duration-200 ease-out",
          open ? "translate-x-0" : "rtl:-translate-x-full ltr:translate-x-full"
        )}
      >
        {device && (
          <>
            {/* Header */}
            <header className="flex items-center justify-between px-5 py-4 border-b border-border">
              <div className="flex items-center gap-3 min-w-0">
                <DeviceTypeIcon type={device.device_type} size={6} />
                <div className="min-w-0">
                  <h3 className="font-bold truncate">{device.display_name}</h3>
                  <p className="text-xs text-fg-muted">{t("detail.title")}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="p-2 rounded-md hover:bg-surface-2 transition-colors"
                aria-label={t("detail.close")}
              >
                <X className="w-5 h-5" />
              </button>
            </header>

            {/* Body */}
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-6">
              {/* Custom name */}
              <Section title={t("detail.customName")}>
                <input
                  type="text"
                  value={customName}
                  onChange={(e) => setCustomName(e.target.value)}
                  placeholder={t("detail.customNamePlaceholder")}
                  className="w-full px-3 py-2 rounded-md border border-border bg-bg text-fg focus:border-primary focus:outline-none"
                />
                <p className="text-xs text-fg-muted mt-1">{t("detail.customNameHint")}</p>
              </Section>

              {/* Notes */}
              <Section title={t("detail.notes")}>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder={t("detail.notesPlaceholder")}
                  rows={4}
                  className="w-full px-3 py-2 rounded-md border border-border bg-bg text-fg focus:border-primary focus:outline-none resize-y"
                />
              </Section>

              {/* Identity */}
              <Section title={t("detail.identity")}>
                <Row label="IP">
                  <span className="font-mono text-sm" dir="ltr">
                    {device.ip}
                  </span>
                </Row>
                <Row label="MAC">
                  <span className="font-mono text-sm text-fg-muted" dir="ltr">
                    {device.mac || "—"}
                  </span>
                </Row>
                <Row label={t("devices.col.host")}>
                  <span className="text-sm">{device.hostname || "—"}</span>
                </Row>
                <Row label={t("devices.col.vendor")}>
                  <span className="text-sm text-fg-muted">{device.vendor || "—"}</span>
                </Row>
                <Row label={t("detail.type")}>
                  <span className="text-sm">{t(`devices.type.${device.device_type}` as never)}</span>
                </Row>
                <Row label={t("devices.col.status")}>
                  {device.status === "online" ? (
                    <span className="badge badge-success">{t("status.online")}</span>
                  ) : (
                    <span className="badge badge-danger">{t("status.offline")}</span>
                  )}
                </Row>
                {device.manageable === false && (
                  <Row label={t("detail.management")}>
                    <span className="badge bg-fg-muted/10 text-fg-muted">
                      {t("devices.notManaged")}
                    </span>
                  </Row>
                )}
                <Row label={t("detail.deviceId")}>
                  <span className="font-mono text-xs text-fg-muted" dir="ltr">
                    #{device.id}
                  </span>
                </Row>
              </Section>

              {/* Timing */}
              <Section title={t("detail.timing")}>
                <Row label={t("detail.firstSeen")}>
                  <span className="text-sm text-fg-muted">
                    {device.first_seen ? formatDateAr(device.first_seen) : "—"}
                  </span>
                </Row>
                <Row label={t("detail.lastSeen")}>
                  <span className="text-sm text-fg-muted">
                    {device.last_seen ? formatDateAr(device.last_seen) : "—"}
                  </span>
                </Row>
              </Section>
            </div>

            {/* Footer with save button */}
            <footer className="px-5 py-4 border-t border-border flex items-center justify-end gap-2">
              {savedFlash && (
                <span className="inline-flex items-center gap-1 text-success text-sm">
                  <CheckCircle2 className="w-4 h-4" />
                  {t("detail.saved")}
                </span>
              )}
              <button
                type="button"
                onClick={onClose}
                className="btn-secondary"
              >
                {t("detail.cancel")}
              </button>
              <button
                type="button"
                onClick={() => save.mutate()}
                disabled={!dirty || save.isPending}
                className="btn-primary inline-flex items-center gap-2"
              >
                {save.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    {t("detail.saving")}
                  </>
                ) : (
                  <>
                    <Save className="w-4 h-4" />
                    {t("detail.save")}
                  </>
                )}
              </button>
            </footer>
          </>
        )}
      </aside>
    </>
  );
}

// ----------------------------------------------------------------
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h4 className="text-xs font-bold text-fg-muted uppercase tracking-wider mb-2">{title}</h4>
      <div className="space-y-1.5">{children}</div>
    </section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <span className="text-xs text-fg-muted flex-shrink-0">{label}</span>
      <span className="text-end truncate">{children}</span>
    </div>
  );
}
