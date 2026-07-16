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
import { useState, type FormEvent, type ReactNode } from "react";

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
      <div className="relative grid min-h-[620px] w-full max-w-5xl overflow-hidden rounded-[2rem] border border-white/70 bg-white shadow-2xl shadow-slate-300/60 lg:grid-cols-[1.03fr_0.97fr]">
        <section className="relative hidden overflow-hidden bg-[#0d1240] p-10 text-white lg:flex lg:flex-col lg:justify-between">
          <div className="pointer-events-none absolute -right-20 -top-24 h-80 w-80 rounded-full bg-[#d9e7ff]/80 blur-sm" />
          <div className="pointer-events-none absolute -bottom-32 -left-24 h-[28rem] w-[28rem] rounded-full bg-[#7287ff]/45" />
          <div className="pointer-events-none absolute left-20 top-20 h-[28rem] w-[20rem] rotate-12 rounded-[45%] bg-[#2943a8]/85" />
          <div className="pointer-events-none absolute bottom-20 right-8 h-48 w-48 rounded-full bg-white/20" />

          <div className="relative inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-white/15 backdrop-blur">
            <ShieldCheck className="h-5 w-5" />
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
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [pendingMfa, setPendingMfa] = useState<MfaRequired | null>(null);

  const signIn = async (nextEmail: string, nextPassword: string) => {
    setSubmitting(true);
    setError(null);
    try {
      const result = await login(nextEmail, nextPassword);
      if (result.status === "mfa_required") {
        setPendingMfa(result);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setSubmitting(false);
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
    await signIn(email, password);
  };

  const onDevLogin = async (account: (typeof DEV_LOGIN_ACCOUNTS)[number]) => {
    setEmail(account.email);
    setPassword(account.password);
    await signIn(account.email, account.password);
  };

  return (
    <AuthShell>
      <form
        onSubmit={onSubmit}
        className="rounded-[1.75rem] border border-white/70 bg-white/90 p-6 shadow-2xl shadow-slate-200/70 backdrop-blur sm:p-8 lg:border-0 lg:p-0 lg:shadow-none"
      >
        <div className="mb-8 lg:hidden">
          <div className="inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">
            <ShieldCheck className="h-3.5 w-3.5" />
            BSG Insights Hub
          </div>
        </div>

        <div className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground">Login</h1>
          <p className="text-sm leading-6 text-muted-foreground">
            Welcome back. Please login to your account.
          </p>
        </div>

        <div className="mt-8 space-y-5">
          <div className="space-y-2">
            <Label htmlFor="email" className="text-sm text-foreground">
              Email address
            </Label>
            <div className="relative">
              <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="email"
                type="email"
                autoComplete="username"
                placeholder="name@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="h-11 bg-white pl-10"
                required
              />
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <Label htmlFor="password" className="text-sm text-foreground">
                Password
              </Label>
              <button
                type="button"
                className="text-xs font-medium text-muted-foreground transition-colors hover:text-primary"
              >
                Forgot password?
              </button>
            </div>
            <div className="relative">
              <LockKeyhole className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-11 bg-white pl-10 pr-11"
                required
              />
              <button
                type="button"
                onClick={() => setShowPassword((value) => !value)}
                className="absolute right-2 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>
        </div>

        <div className="mt-4 flex items-center justify-between gap-3 text-xs">
          <label className="inline-flex items-center gap-2 text-muted-foreground">
            <input
              type="checkbox"
              checked={rememberMe}
              onChange={(event) => setRememberMe(event.target.checked)}
              className="h-3.5 w-3.5 rounded border-border accent-primary"
            />
            Remember me
          </label>
          <span className="text-muted-foreground">Secure BSG access</span>
        </div>

        {error && (
          <div className="mt-5 flex gap-3 rounded-xl border border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <p>{error}</p>
          </div>
        )}

        <Button type="submit" className="mt-6 h-11 w-full text-sm" disabled={submitting}>
          {submitting ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Signing in
            </>
          ) : (
            <>
              Continue
              <ArrowRight className="h-4 w-4" />
            </>
          )}
        </Button>

        {isDevLoginEnabled && (
          <div className="mt-6 space-y-3 rounded-2xl border border-dashed border-border bg-muted/40 p-4">
            <div>
              <p className="text-sm font-semibold text-foreground">Development shortcuts</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                Pick a persona to sign in quickly. Shared password:{" "}
                <span className="font-mono text-foreground">{DEV_LOGIN_ACCOUNTS[0]?.password}</span>
              </p>
            </div>
            <div className="grid gap-2">
              {DEV_LOGIN_ACCOUNTS.map((account) => (
                <button
                  key={account.email}
                  type="button"
                  disabled={submitting}
                  onClick={() => void onDevLogin(account)}
                  className="group flex w-full items-center justify-between gap-3 rounded-xl border border-border bg-white px-3 py-3 text-left text-sm transition-colors hover:border-primary/30 hover:bg-primary/5 disabled:opacity-50"
                >
                  <span>
                    <span className="block font-medium text-foreground">{account.label}</span>
                    <span className="font-mono text-xs text-muted-foreground">{account.email}</span>
                  </span>
                  <ArrowRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                </button>
              ))}
            </div>
          </div>
        )}

        <p className="mt-6 text-center text-xs leading-5 text-muted-foreground">
          Need access? Contact your BSG administrator to activate your workspace role.
        </p>
      </form>
    </AuthShell>
  );
}
