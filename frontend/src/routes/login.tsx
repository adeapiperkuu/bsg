import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";

import { DEV_LOGIN_ACCOUNTS, isDevLoginEnabled } from "@/lib/dev-login";
import { useAuthStore } from "@/stores/useAuthStore";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/login")({
  component: LoginPage,
});

function LoginPage() {
  const login = useAuthStore((s) => s.login);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const signIn = async (nextEmail: string, nextPassword: string) => {
    setSubmitting(true);
    setError(null);
    try {
      await login(nextEmail, nextPassword);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setSubmitting(false);
    }
  };

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    await signIn(email, password);
  };

  const onDevLogin = async (account: (typeof DEV_LOGIN_ACCOUNTS)[number]) => {
    setEmail(account.email);
    setPassword(account.password);
    await signIn(account.email, account.password);
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm space-y-4 rounded-lg border border-border bg-card p-6 shadow-sm"
      >
        <div>
          <h1 className="text-lg font-semibold text-foreground">Sign in</h1>
          <p className="mt-1 text-sm text-muted-foreground">Operations Tower — BSG Insights Hub</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </Button>
        {isDevLoginEnabled && (
          <div className="space-y-3 border-t border-border pt-4">
            <div>
              <p className="text-sm font-medium text-foreground">Dev accounts</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Password for all:{" "}
                <span className="font-mono">{DEV_LOGIN_ACCOUNTS[0]?.password}</span>
              </p>
            </div>
            <div className="space-y-2">
              {DEV_LOGIN_ACCOUNTS.map((account) => (
                <button
                  key={account.email}
                  type="button"
                  disabled={submitting}
                  onClick={() => void onDevLogin(account)}
                  className="flex w-full items-center justify-between rounded-md border border-border bg-muted/40 px-3 py-2 text-left text-sm transition-colors hover:bg-muted disabled:opacity-50"
                >
                  <span className="font-medium text-foreground">{account.label}</span>
                  <span className="font-mono text-xs text-muted-foreground">{account.email}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </form>
    </div>
  );
}
