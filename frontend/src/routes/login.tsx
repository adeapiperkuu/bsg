import { createFileRoute } from "@tanstack/react-router";
import {
  AlertCircle,
  ArrowRight,
  Eye,
  EyeOff,
  Loader2,
  LockKeyhole,
  Mail,
  ShieldCheck,
} from "lucide-react";
import { useId, useState, type FormEvent, type ReactNode } from "react";

import { MfaStep } from "@/components/auth/MfaStep";
import { DEV_LOGIN_ACCOUNTS, isDevLoginEnabled } from "@/lib/dev-login";
import { useAuthStore } from "@/stores/useAuthStore";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { MfaRequired } from "@/types/auth";

export const Route = createFileRoute("/login")({
  component: LoginPage,
});

function AuthShell({ children }: { children: ReactNode }) {
  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#f4f6fb] px-4 py-8 text-foreground sm:px-6">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(13,18,64,0.13),transparent_32%),radial-gradient(circle_at_bottom_right,rgba(59,130,246,0.12),transparent_30%)]" />
      <div className="relative grid w-full max-w-5xl overflow-hidden rounded-[2rem] border border-white/70 bg-white shadow-2xl shadow-slate-300/60 lg:min-h-[640px] lg:grid-cols-[1.03fr_0.97fr]">
        <section className="relative hidden overflow-hidden bg-[#0d1240] p-10 text-white lg:flex lg:flex-col lg:justify-between">
          <div className="pointer-events-none absolute -right-20 -top-24 h-80 w-80 rounded-full bg-[#d9e7ff]/80 blur-sm" />
          <div className="pointer-events-none absolute -bottom-32 -left-24 h-[28rem] w-[28rem] rounded-full bg-[#7287ff]/45" />
          <div className="pointer-events-none absolute left-20 top-20 h-[28rem] w-[20rem] rotate-12 rounded-[45%] bg-[#2943a8]/85" />
          <div className="pointer-events-none absolute bottom-20 right-8 h-48 w-48 rounded-full bg-white/20" />

          <div className="relative inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-white/15 backdrop-blur">
            <ShieldCheck className="h-5 w-5" aria-hidden />
          </div>

          <div className="relative max-w-sm pb-8">
            <p className="text-sm font-medium uppercase tracking-[0.24em] text-white/65">
              BSG Insights Hub
            </p>
            <h1 className="mt-5 text-6xl font-semibold leading-[0.95] tracking-tight">
              Welcome
              <br />
              Back!
            </h1>
            <p className="mt-6 text-sm leading-6 text-white/70">
              Your secure entry point for delivery governance, operational knowledge, and quality
              intelligence.
            </p>
          </div>
        </section>

        <section className="flex items-center justify-center px-6 py-10 sm:px-10 lg:px-14">
          <div className="w-full max-w-sm">{children}</div>
        </section>
      </div>
    </main>
  );
}

function LoginPage() {
  const login = useAuthStore((s) => s.login);
  const errorId = useId();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [signingInAs, setSigningInAs] = useState<string | null>(null);
  const [pendingMfa, setPendingMfa] = useState<MfaRequired | null>(null);

  const signIn = async (nextEmail: string, nextPassword: string) => {
    setSubmitting(true);
    setSigningInAs(nextEmail);
    setError(null);
    try {
      const result = await login(nextEmail, nextPassword);
      if (result.status === "mfa_required") {
        setPendingMfa(result);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed. Check your email and password, then try again.");
    } finally {
      setSubmitting(false);
      setSigningInAs(null);
    }
  };

  if (pendingMfa) {
    return (
      <AuthShell>
        <MfaStep pending={pendingMfa} onComplete={() => setPendingMfa(null)} />
      </AuthShell>
    );
  }

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    await signIn(email.trim(), password);
  };

  const onDevLogin = async (account: (typeof DEV_LOGIN_ACCOUNTS)[number]) => {
    setEmail(account.email);
    setPassword(account.password);
    await signIn(account.email, account.password);
  };

  const submitLabel = submitting
    ? signingInAs
      ? `Signing in as ${signingInAs.split("@")[0]}…`
      : "Signing in…"
    : "Sign in";

  return (
    <AuthShell>
      <form
        onSubmit={onSubmit}
        aria-busy={submitting}
        className="space-y-6"
      >
        <div className="lg:hidden">
          <div className="inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
            BSG Insights Hub
          </div>
        </div>

        <header className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground">Sign in</h1>
          <p className="text-sm leading-6 text-muted-foreground">
            Enter your work email to access your BSG workspace.
          </p>
        </header>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="email" className="text-sm font-medium text-foreground">
              Email address
            </Label>
            <div className="flex h-11 items-center gap-3 rounded-xl border border-input bg-white px-3 shadow-sm transition-colors focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/20 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50 has-[[aria-invalid=true]]:border-destructive/50 has-[[aria-invalid=true]]:ring-2 has-[[aria-invalid=true]]:ring-destructive/20">
              <Mail className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <Input
                id="email"
                type="email"
                autoComplete="username"
                autoFocus
                placeholder="name@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="h-full min-w-0 flex-1 border-0 bg-white p-0 shadow-none focus-visible:ring-0 md:text-sm"
                required
                disabled={submitting}
                aria-invalid={Boolean(error)}
                aria-describedby={error ? errorId : undefined}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="password" className="text-sm font-medium text-foreground">
              Password
            </Label>
            <div className="flex h-11 items-center gap-3 rounded-xl border border-input bg-white px-3 shadow-sm transition-colors focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/20 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50 has-[[aria-invalid=true]]:border-destructive/50 has-[[aria-invalid=true]]:ring-2 has-[[aria-invalid=true]]:ring-destructive/20">
              <LockKeyhole className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <Input
                id="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-full min-w-0 flex-1 border-0 bg-white p-0 shadow-none focus-visible:ring-0 md:text-sm"
                required
                disabled={submitting}
                aria-invalid={Boolean(error)}
                aria-describedby={error ? errorId : undefined}
              />
              <button
                type="button"
                onClick={() => setShowPassword((value) => !value)}
                disabled={submitting}
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          <label className="inline-flex items-center gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={rememberMe}
              onChange={(event) => setRememberMe(event.target.checked)}
              disabled={submitting}
              className="h-4 w-4 rounded border-border accent-primary"
            />
            Keep me signed in on this device
          </label>
        </div>

        {error && (
          <div
            id={errorId}
            role="alert"
            className="flex gap-3 rounded-xl border border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <div className="space-y-1">
              <p className="font-medium">Couldn’t sign in</p>
              <p className="text-destructive/90">{error}</p>
            </div>
          </div>
        )}

        <div className="space-y-3">
          <Button type="submit" className="h-11 w-full text-sm" disabled={submitting}>
            {submitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                {submitLabel}
              </>
            ) : (
              <>
                Sign in
                <ArrowRight className="h-4 w-4" aria-hidden />
              </>
            )}
          </Button>
          <p className="flex items-center justify-center gap-1.5 text-xs text-muted-foreground">
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
            Encrypted session · Role-based access
          </p>
        </div>

        {isDevLoginEnabled && (
          <fieldset
            disabled={submitting}
            className="space-y-3 rounded-2xl border border-dashed border-border bg-muted/30 p-4 disabled:opacity-60"
          >
            <legend className="px-1 text-sm font-semibold text-foreground">
              Quick demo access
            </legend>
            <p className="text-xs leading-5 text-muted-foreground">
              Local development only. Choose a role — credentials are filled for you.
            </p>
            <div className="grid grid-cols-3 gap-2" role="group" aria-label="Demo personas">
              {DEV_LOGIN_ACCOUNTS.map((account) => {
                const isActive = submitting && signingInAs === account.email;
                return (
                  <button
                    key={account.email}
                    type="button"
                    onClick={() => void onDevLogin(account)}
                    aria-label={`Sign in as ${account.label} (${account.email})`}
                    className="flex flex-col items-center justify-center gap-1 rounded-xl border border-border bg-white px-2 py-3 text-center transition-colors hover:border-primary/40 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed"
                  >
                    {isActive ? (
                      <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden />
                    ) : (
                      <span className="text-sm font-semibold text-foreground">{account.label}</span>
                    )}
                    <span className="max-w-full truncate text-[10px] text-muted-foreground">
                      {account.email.split("@")[0]}
                    </span>
                  </button>
                );
              })}
            </div>
          </fieldset>
        )}

        <p className="text-center text-xs leading-5 text-muted-foreground">
          Need access? Ask your BSG administrator to activate your workspace role.
          Password help is handled by your admin.
        </p>
      </form>
    </AuthShell>
  );
}
