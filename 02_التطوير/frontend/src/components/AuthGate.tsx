import { useEffect, useState, type ReactNode } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Loader2, Lock, ShieldCheck, KeyRound, AlertTriangle } from "lucide-react";
import { apiFetch, authToken, setAuthToken } from "@/lib/utils";

interface AuthStatus {
  password_set: boolean;
}

/**
 * App-level login gate. Renders the children only once the user is
 * authenticated; otherwise shows the first-run setup screen (no password yet)
 * or the login screen. See backend services/auth.py.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const hasToken = authToken() !== "";
  const [authed, setAuthed] = useState(false);

  const status = useQuery<AuthStatus>({
    queryKey: ["auth-status"],
    queryFn: () => apiFetch<AuthStatus>("/api/auth/status"),
    retry: false,
    staleTime: Infinity,
  });

  // Validate a stored token up front against the gated /check endpoint, so we
  // never flash the app on a stale session (e.g. after a backend restart).
  const check = useQuery<{ ok: boolean }>({
    queryKey: ["auth-check"],
    queryFn: () => apiFetch<{ ok: boolean }>("/api/auth/check"),
    enabled: hasToken,
    retry: false,
    staleTime: Infinity,
  });

  useEffect(() => {
    if (check.isSuccess) setAuthed(true);
    else if (check.isError) {
      setAuthToken(""); // stale/invalid token — drop it and show the login screen
      setAuthed(false);
    }
  }, [check.isSuccess, check.isError]);

  useEffect(() => {
    const onUnauth = () => setAuthed(false);
    window.addEventListener("hu:unauthorized", onUnauth);
    return () => window.removeEventListener("hu:unauthorized", onUnauth);
  }, []);

  // Still resolving whether a password exists, or validating an existing token.
  if (status.isLoading || (hasToken && check.isLoading)) {
    return (
      <Centered>
        <Loader2 className="w-8 h-8 animate-spin text-fg-muted" />
      </Centered>
    );
  }

  // Only render the app once we've confirmed authentication (via a valid stored
  // token or a fresh login/setup) — never optimistically.
  if (authed) return <>{children}</>;

  const passwordSet = status.data?.password_set ?? false;
  return (
    <AuthForm
      mode={passwordSet ? "login" : "setup"}
      onAuthed={(token) => {
        setAuthToken(token);
        setAuthed(true);
      }}
    />
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-bg text-fg flex items-center justify-center p-4">{children}</div>
  );
}

function AuthForm({
  mode,
  onAuthed,
}: {
  mode: "setup" | "login";
  onAuthed: (token: string) => void;
}) {
  const { t } = useTranslation();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [clientError, setClientError] = useState("");

  const isSetup = mode === "setup";

  const submit = useMutation<{ token: string }, Error>({
    mutationFn: () =>
      apiFetch<{ token: string }>(isSetup ? "/api/auth/setup" : "/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ password }),
      }),
    onSuccess: (data) => onAuthed(data.token),
  });

  const onSubmit = () => {
    setClientError("");
    if (isSetup) {
      if (password.length < 6) return setClientError(t("auth.tooShort"));
      if (password !== confirm) return setClientError(t("auth.mismatch"));
    }
    submit.mutate();
  };

  const canSubmit = isSetup
    ? password.length >= 6 && confirm.length >= 6
    : password.length >= 1;

  return (
    <Centered>
      <div className="card w-full max-w-sm">
        <div className="flex flex-col items-center text-center mb-5">
          <div className="w-14 h-14 rounded-2xl bg-primary/15 text-primary flex items-center justify-center mb-3">
            {isSetup ? <ShieldCheck className="w-7 h-7" /> : <Lock className="w-7 h-7" />}
          </div>
          <h1 className="text-xl font-display font-bold">
            {isSetup ? t("auth.setupTitle") : t("auth.loginTitle")}
          </h1>
          <p className="text-sm text-fg-muted mt-1">
            {isSetup ? t("auth.setupSubtitle") : t("auth.loginSubtitle")}
          </p>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (canSubmit && !submit.isPending) onSubmit();
          }}
          className="space-y-3"
        >
          <div>
            <label htmlFor="auth-password" className="text-xs font-bold text-fg-muted mb-1 block">
              {t("auth.passwordLabel")}
            </label>
            <input
              id="auth-password"
              type="password"
              autoFocus
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t("auth.passwordPlaceholder")}
              className="w-full px-3 py-2 rounded-md border border-border bg-bg text-fg focus:border-primary focus:outline-none"
            />
          </div>

          {isSetup && (
            <div>
              <label htmlFor="auth-confirm" className="text-xs font-bold text-fg-muted mb-1 block">
                {t("auth.confirmLabel")}
              </label>
              <input
                id="auth-confirm"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder={t("auth.passwordPlaceholder")}
                className="w-full px-3 py-2 rounded-md border border-border bg-bg text-fg focus:border-primary focus:outline-none"
              />
              <p className="text-[11px] text-fg-subtle mt-1">{t("auth.minHint")}</p>
            </div>
          )}

          {(clientError || submit.isError) && (
            <div className="p-2.5 rounded-md bg-danger/10 border border-danger/30 text-danger text-sm flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span>{clientError || (submit.error as Error)?.message}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={!canSubmit || submit.isPending}
            className="btn-primary w-full inline-flex items-center justify-center gap-2"
          >
            {submit.isPending ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {t("auth.working")}
              </>
            ) : (
              <>
                <KeyRound className="w-4 h-4" />
                {isSetup ? t("auth.createBtn") : t("auth.loginBtn")}
              </>
            )}
          </button>
        </form>

        {!isSetup && <p className="text-[11px] text-fg-subtle text-center mt-4">{t("auth.forgot")}</p>}
      </div>
    </Centered>
  );
}
