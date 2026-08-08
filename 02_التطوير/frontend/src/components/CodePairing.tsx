import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Check, KeyRound, Loader2, RefreshCw, Smartphone } from "lucide-react";
import { apiFetch, cn, type ApiError } from "@/lib/utils";

// ================================================================
// إقران الهاتف برمز سداسيّ — بلا mDNS وبلا خبرة.
//
// المسار الوحيد الذي يعمل على شبكة لا تمرّر البثّ المتعدّد بين اللاسلكيّ والسلكيّ،
// وهي حالة شبكة العميل الأولى المقيسة: الهاتف يستجيب للping في ٤٠ م.ث ولا يرسل
// حزمة mDNS واحدة في ٦٠ ثانية.
//
// وما يقرّر تصميم هذه اللوحة أن مَن يستعملها **لا خبرة تقنيّة عنده**:
//   • لا يكتب عنوانًا — يختار هاتفه من قائمة يعرفها التطبيق من فحص الشبكة.
//   • لا يقرأ منفذًا — التطبيق يجده بنفسه (٢٠ ألف منفذ في ١٦ ثانية، مقيسة).
//   • لا يلمس إعدادات راوتر.
// يكتب ستّة أرقام، وينتهي الأمر بالهاتف في القائمة.
// ================================================================

interface Candidate {
  ip: string;
  name: string;
  vendor: string;
  device_type: string;
  already_added: boolean;
}

export function CodePairing({ onAdded }: { onAdded: () => void }) {
  const { t } = useTranslation();
  const [host, setHost] = useState("");
  const [code, setCode] = useState("");

  const candidates = useQuery<{ candidates: Candidate[]; total: number }>({
    queryKey: ["android-pair-candidates"],
    queryFn: () => apiFetch("/api/android/pair/candidates"),
  });

  const pair = useMutation<{ device: { host: string; port: number } }, ApiError, void>({
    mutationFn: () =>
      apiFetch("/api/android/pair/auto", {
        method: "POST",
        body: JSON.stringify({ host, code: code.trim() }),
      }),
    onSuccess: () => onAdded(),
  });

  const list = candidates.data?.candidates ?? [];
  const phones = list.filter((c) => c.device_type === "phone" && !c.already_added);
  const rest = list.filter((c) => c.device_type !== "phone" || c.already_added);
  const canPair = /^\d{1,3}(\.\d{1,3}){3}$/.test(host) && /^\d{6}$/.test(code.trim());

  return (
    <div className="mb-3 p-3 rounded-md border border-success/40 bg-success/5 space-y-3">
      <div className="flex items-center gap-2 text-xs font-bold text-fg">
        <KeyRound className="w-4 h-4 text-success" />
        {t("android.code.title")}
      </div>
      <p className="text-xs text-fg-muted">{t("android.code.intro")}</p>

      {/* 1 — pick the phone. Never type an address. */}
      <div>
        <label className="text-[11px] text-fg-muted mb-1 block" htmlFor="code-pair-host">
          {t("android.code.pickPhone")}
        </label>
        {candidates.isLoading ? (
          <p className="text-xs text-fg-muted inline-flex items-center gap-2">
            <Loader2 className="w-3 h-3 animate-spin" /> {t("status.loading")}
          </p>
        ) : list.length === 0 ? (
          <p className="text-xs text-warning">{t("android.code.noDevices")}</p>
        ) : (
          <select
            id="code-pair-host"
            value={host}
            onChange={(e) => setHost(e.target.value)}
            className="w-full px-3 py-2 rounded-md border border-border bg-bg text-fg focus:border-primary focus:outline-none text-sm"
          >
            <option value="">{t("android.code.pickPlaceholder")}</option>
            {phones.length > 0 && (
              <optgroup label={t("android.code.groupPhones")}>
                {phones.map((c) => (
                  <option key={c.ip} value={c.ip}>
                    {c.name} — {c.ip}
                  </option>
                ))}
              </optgroup>
            )}
            {rest.length > 0 && (
              <optgroup label={t("android.code.groupOther")}>
                {rest.map((c) => (
                  <option key={c.ip} value={c.ip}>
                    {c.name} — {c.ip}
                    {c.already_added ? ` (${t("android.code.alreadyAdded")})` : ""}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        )}
        <button
          type="button"
          onClick={() => candidates.refetch()}
          className="btn-secondary text-[11px] mt-1 inline-flex items-center gap-1"
        >
          <RefreshCw className="w-3 h-3" />
          {t("android.code.rescan")}
        </button>
      </div>

      {/* 2 — the one thing the operator reads. */}
      <ol className="text-xs text-fg-muted space-y-1 list-decimal ms-4">
        <li>{t("android.code.step1")}</li>
        <li>{t("android.code.step2")}</li>
      </ol>

      <div className="flex items-end gap-2 flex-wrap">
        <div>
          <label className="text-[11px] text-fg-muted mb-1 block" htmlFor="code-pair-code">
            {t("android.code.codeLabel")}
          </label>
          <input
            id="code-pair-code"
            type="text"
            inputMode="numeric"
            dir="ltr"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            placeholder="123456"
            className="px-3 py-2 rounded-md border border-border bg-bg text-fg focus:border-primary focus:outline-none font-mono text-lg tracking-widest w-36"
          />
        </div>
        <button
          type="button"
          onClick={() => pair.mutate()}
          disabled={!canPair || pair.isPending}
          className="btn-primary inline-flex items-center gap-2"
        >
          {pair.isPending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Smartphone className="w-4 h-4" />
          )}
          {t("android.code.pairBtn")}
        </button>
      </div>

      {pair.isPending && (
        // The scan takes about twenty seconds. Saying so is the difference between
        // waiting and deciding it has hung.
        <p className="text-xs text-fg-muted inline-flex items-center gap-2">
          <Loader2 className="w-3 h-3 animate-spin" />
          {t("android.code.working")}
        </p>
      )}
      {pair.isSuccess && (
        <p className="text-xs text-success inline-flex items-center gap-1">
          <Check className="w-4 h-4" />
          {t("android.code.done")}
        </p>
      )}
      {pair.isError && <p className="text-xs text-danger">{pair.error.message}</p>}

      <p className={cn("text-[11px] text-fg-subtle")}>{t("android.code.whyThisWorks")}</p>
    </div>
  );
}
