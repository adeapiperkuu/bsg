import { useEffect, useState } from "react";
import { AlertCircle, KeyRound, Loader2, ShieldCheck, Smartphone } from "lucide-react";

import { mfaChallenge, mfaEnroll, mfaVerify } from "@/lib/api";
import { useAuthStore } from "@/stores/useAuthStore";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { MfaRequired } from "@/types/auth";

/** DEVELOPMENT_PLAN.md Workstream E. Shown after POST /auth/login returns
 * `mfa_required`. `stage: "enroll"` means no verified TOTP factor exists yet
 * (show QR + secret, then ask for a code to activate it); `stage:
 * "challenge"` means one already exists (ask for a code only). Both paths
 * converge on the same "enter code" step -- a fresh challenge is requested
 * right before each verify attempt, so a failed/expired code can just be
 * retried without any stale challenge_id bookkeeping. */
export function MfaStep({ pending, onComplete }: { pending: MfaRequired; onComplete: () => void }) {
  const completeMfaLogin = useAuthStore((s) => s.completeMfaLogin);
  const [factorId, setFactorId] = useState<string | null>(pending.factor_id);
  const [qrCode, setQrCode] = useState<string | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const enrolling = pending.stage === "enroll";

  useEffect(() => {
    if (!enrolling) return;
    let cancelled = false;
    setSubmitting(true);
    setError(null);
    mfaEnroll(pending.pending_token)
      .then((enrollment) => {
        if (cancelled) return;
        setFactorId(enrollment.factor_id);
        setQrCode(enrollment.qr_code);
        setSecret(enrollment.secret);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Could not start MFA enrollment.");
      })
      .finally(() => {
        if (!cancelled) setSubmitting(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending.pending_token]);

  const submitCode = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!factorId) return;
    setSubmitting(true);
    setError(null);
    try {
      const challenge = await mfaChallenge(pending.pending_token, factorId);
      await mfaVerify(pending.pending_token, factorId, challenge.challenge_id, code);
      await completeMfaLogin();
      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid or expired code. Try again.");
      setCode("");
    } finally {
      setSubmitting(false);
    }
  };

  const qrSrc = qrCode
    ? qrCode.startsWith("data:")
      ? qrCode
      : `data:image/svg+xml;utf8,${encodeURIComponent(qrCode)}`
    : null;

  return (
    <form
      onSubmit={submitCode}
      className="rounded-[1.75rem] border border-white/70 bg-white/90 p-6 shadow-2xl shadow-slate-200/80 backdrop-blur sm:p-8"
    >
      <div className="mb-8 inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">
        <ShieldCheck className="h-3.5 w-3.5" />
        Secure sign-in
      </div>

      <div className="space-y-2">
        <p className="text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Final step
        </p>
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">
          Verify it&apos;s you
        </h1>
        <p className="text-sm leading-6 text-muted-foreground">
          {enrolling
            ? "Scan the QR code with your authenticator app, then enter the 6-digit code it shows."
            : "Enter the 6-digit code from your authenticator app."}
        </p>
      </div>

      {enrolling && qrSrc && (
        <div className="mt-6 space-y-4 rounded-2xl border border-border bg-muted/40 p-4">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground">
            <Smartphone className="h-4 w-4 text-primary" />
            Set up an authenticator app
          </div>
          <div className="rounded-xl bg-white p-4">
            <img src={qrSrc} alt="MFA enrollment QR code" className="mx-auto h-40 w-40" />
          </div>
          {secret && (
            <p className="break-words text-center text-xs leading-5 text-muted-foreground">
              Can&apos;t scan it? Enter this key manually:{" "}
              <span className="font-mono text-foreground">{secret}</span>
            </p>
          )}
        </div>
      )}

      {enrolling && !qrSrc && !error && (
        <div className="mt-6 flex items-center gap-2 rounded-2xl border border-border bg-muted/40 p-4 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Setting up your authenticator...
        </div>
      )}

      <div className="mt-6 space-y-2">
        <Label htmlFor="mfa-code" className="text-sm text-foreground">
          Authentication code
        </Label>
        <div className="relative">
          <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            id="mfa-code"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            placeholder="000000"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            className="h-11 bg-white pl-10 text-center font-mono text-lg tracking-[0.35em]"
            required
            disabled={!factorId}
          />
        </div>
      </div>

      {error && (
        <div className="mt-5 flex gap-3 rounded-xl border border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <p>{error}</p>
        </div>
      )}

      <Button
        type="submit"
        className="mt-6 h-11 w-full"
        disabled={submitting || !factorId || code.length !== 6}
      >
        {submitting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Verifying
          </>
        ) : (
          "Verify and sign in"
        )}
      </Button>

      <p className="mt-6 text-center text-xs leading-5 text-muted-foreground">
        Codes refresh every 30 seconds. If one expires, enter the next code from your app.
      </p>
    </form>
  );
}
