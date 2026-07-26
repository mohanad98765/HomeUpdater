import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Check, Loader2, QrCode, RefreshCw, Smartphone, X } from "lucide-react";
import { apiFetch, cn, type ApiError } from "@/lib/utils";

// ================================================================
// إقران الهاتف برمز QR.
//
// المسار اليدويّ يطلب من إنسان أن ينقل ثلاثة أشياء من شاشة هاتف: عنوانًا،
// ومنفذ إقران يتغيّر كل مرّة، ورمزًا ينتهي. وهذا القسم يحذفها.
//
// وثلاثة أشياء هنا مقصودة:
//   • المركز لا يستطيع أن يعرف لماذا لم يصل شيء. `adb mdns check` مخرَجه نصّ ثابت
//     ينجح دائمًا، فجدارُ حماية وشبكةٌ أخرى وهاتفٌ لم يُفتَح فيه شيء تبدو سواءً.
//     فالنصّ يقول ذلك بدل أن يخمّن.
//   • تفعيل «خيارات المطوّر» و«تصحيح الأخطاء اللاسلكي» **ليس** من عمل هذه الصفحة،
//     فهي تقول الطريق إليهما صراحةً بدل أن تفترضهما.
//   • عند وصول هاتفين معًا يُسأل المشغّل — لأن الإقران بقرعة يسلّم كلمة المرور
//     لهاتف لم يقصده.
// ================================================================

interface Candidate {
  instance: string;
  address: string;
  port: number;
}
interface QrSession {
  id?: string;
  payload?: string;
  status: "none" | "waiting" | "choose" | "pairing" | "paired" | "failed" | "expired";
  expires_at?: string;
  seconds_left?: number;
  candidates?: Candidate[];
  device?: { host: string; port: number | null; instance: string } | null;
  error?: string;
}

export function QrPairing({
  onPaired,
}: {
  /** Called with the phone's address once pairing succeeds, so the dialog can fill in
   *  the connect port and let the operator add it without retyping anything. */
  onPaired: (host: string, port: number | null) => void;
}) {
  const { t } = useTranslation();
  const [active, setActive] = useState(false);
  const [svgKey, setSvgKey] = useState(0);

  const session = useQuery<QrSession>({
    queryKey: ["android-qr"],
    queryFn: () => apiFetch<QrSession>("/api/android/pair/qr"),
    enabled: active,
    // The phone arrives within a second or two of the scan, and that moment is the
    // whole point of the panel.
    refetchInterval: active ? 1500 : false,
  });

  const start = useMutation<QrSession, ApiError, void>({
    mutationFn: () => apiFetch<QrSession>("/api/android/pair/qr", { method: "POST" }),
    onSuccess: () => {
      setActive(true);
      setSvgKey((k) => k + 1);
    },
  });

  const choose = useMutation<QrSession, ApiError, string>({
    mutationFn: (instance) =>
      apiFetch<QrSession>("/api/android/pair/qr/choose", {
        method: "POST",
        body: JSON.stringify({ instance }),
      }),
  });

  const cancel = useMutation({
    mutationFn: () => apiFetch("/api/android/pair/qr", { method: "DELETE" }),
    onSuccess: () => setActive(false),
  });

  const status = session.data?.status ?? "none";

  // A pairing code left live is a code someone else can use, so closing the dialog ends
  // the session rather than leaving it to time out.
  useEffect(() => {
    return () => {
      void apiFetch("/api/android/pair/qr", { method: "DELETE" }).catch(() => {});
    };
  }, []);

  useEffect(() => {
    if (status === "paired" && session.data?.device) {
      onPaired(session.data.device.host, session.data.device.port);
      setActive(false);
    }
  }, [status, session.data, onPaired]);

  if (!active || status === "none") {
    return (
      <div className="mb-3 p-3 rounded-md border border-primary/40 bg-primary/5 space-y-2">
        <div className="flex items-center gap-2 text-xs font-bold text-fg">
          <QrCode className="w-4 h-4 text-primary" />
          {t("android.qr.title")}
        </div>
        <p className="text-xs text-fg-muted">{t("android.qr.intro")}</p>
        <button
          type="button"
          onClick={() => start.mutate()}
          disabled={start.isPending}
          className="btn-primary text-sm inline-flex items-center gap-2"
        >
          {start.isPending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <QrCode className="w-4 h-4" />
          )}
          {t("android.qr.startBtn")}
        </button>
        {start.isError && (
          <p className="text-xs text-danger">
            {t("android.qr.startFailed")} {start.error.message}
          </p>
        )}
      </div>
    );
  }

  const left = session.data?.seconds_left ?? 0;
  const clock = `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`;

  return (
    <div className="mb-3 p-3 rounded-md border border-primary/40 bg-primary/5 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-bold text-fg">
          <QrCode className="w-4 h-4 text-primary" />
          {t("android.qr.title")}
        </div>
        <button
          type="button"
          onClick={() => cancel.mutate()}
          className="p-1 rounded-md hover:bg-surface-2 transition-colors"
          aria-label={t("android.qr.cancelBtn")}
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {(status === "waiting" || status === "pairing") && (
        <>
          <ol className="text-xs text-fg-muted space-y-1 list-decimal ms-4">
            <li>{t("android.qr.step1")}</li>
            <li>{t("android.qr.step2")}</li>
            <li>{t("android.qr.step3")}</li>
          </ol>

          <div className="flex justify-center">
            {/* Keyed so a new session refetches the image instead of showing the old
                code, which would pair nothing and look like a broken feature. */}
            <img
              key={svgKey}
              src={`/api/android/pair/qr.svg?s=${svgKey}`}
              alt={t("android.qr.imageAlt")}
              width={246}
              height={246}
              className="rounded-md bg-white p-2"
            />
          </div>

          <p
            className={cn(
              "text-xs text-center",
              left <= 20 ? "text-danger" : "text-fg-muted",
            )}
          >
            {status === "pairing"
              ? t("android.qr.pairingNow")
              : t("android.qr.expiresIn", { clock })}
          </p>

          <details className="text-xs">
            <summary className="cursor-pointer text-fg-muted">
              {t("android.qr.whereIsIt")}
            </summary>
            <p className="mt-1 text-fg-subtle">{t("android.qr.whereIsItBody")}</p>
          </details>
        </>
      )}

      {status === "choose" && (
        <div className="space-y-2">
          <p className="text-xs text-warning inline-flex items-start gap-1">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            {t("android.qr.chooseBody")}
          </p>
          {(session.data?.candidates ?? []).map((c) => (
            <button
              key={c.instance}
              type="button"
              onClick={() => choose.mutate(c.instance)}
              disabled={choose.isPending}
              className="btn-secondary w-full text-start text-xs inline-flex items-center gap-2"
            >
              <Smartphone className="w-4 h-4" />
              <span dir="ltr" className="font-mono">
                {c.instance} — {c.address}
              </span>
            </button>
          ))}
        </div>
      )}

      {status === "paired" && (
        <p className="text-xs text-success inline-flex items-center gap-1">
          <Check className="w-4 h-4" />
          {t("android.qr.paired")}
        </p>
      )}

      {(status === "expired" || status === "failed") && (
        <div className="space-y-2">
          <p className="text-xs text-danger">
            {status === "expired" ? t("android.qr.expired") : t("android.qr.failed")}
          </p>
          {session.data?.error && (
            <p className="text-xs text-fg-subtle font-mono" dir="ltr">
              {session.data.error}
            </p>
          )}
          {/* The hub cannot distinguish these, so it lists them instead of picking one. */}
          <ul className="text-xs text-fg-muted space-y-1 list-disc ms-4">
            <li>{t("android.qr.why1")}</li>
            <li>{t("android.qr.why2")}</li>
            <li>{t("android.qr.why3")}</li>
            <li>{t("android.qr.why4")}</li>
          </ul>
          <button
            type="button"
            onClick={() => start.mutate()}
            className="btn-secondary text-sm inline-flex items-center gap-2"
          >
            <RefreshCw className="w-4 h-4" />
            {t("android.qr.again")}
          </button>
        </div>
      )}
    </div>
  );
}
