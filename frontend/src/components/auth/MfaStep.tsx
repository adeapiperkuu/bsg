import { useEffect, useState } from "react";

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
    <form onSubmit={submitCode} className="w-full max-w-sm space-y-4 rounded-lg border border-border bg-card p-6 shadow-sm">
      <div>
        <h1 className="text-lg font-semibold text-foreground">Two-factor authentication</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {enrolling
            ? "Scan the QR code with an authenticator app, then enter the 6-digit code it shows."
            : "Enter the 6-digit code from your authenticator app."}
        </p>
      </div>

      {enrolling && qrSrc && (
        <div className="space-y-2 rounded-md border border-border bg-muted/30 p-4">
          <img src={qrSrc} alt="MFA enrollment QR code" className="mx-auto h-40 w-40" />
          {secret && (
            <p className="text-center text-xs text-muted-foreground">
              Can't scan it? Enter this key manually: <span className="font-mono">{secret}</span>
            </p>
          )}
        </div>
      )}

      {enrolling && !qrSrc && !error && (
        <p className="text-sm text-muted-foreground">Setting up your authenticator...</p>
      )}

      <div className="space-y-2">
        <Label htmlFor="mfa-code">Authentication code</Label>
        <Input
          id="mfa-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          required
          disabled={!factorId}
        />
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <Button type="submit" className="w-full" disabled={submitting || !factorId || code.length !== 6}>
        {submitting ? "Verifying…" : "Verify and sign in"}
      </Button>
    </form>
  );
}
