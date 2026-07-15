import { useEffect } from "react";
import { useNavigate } from "@tanstack/react-router";

import { canAccessPath, defaultRouteForRole } from "@/lib/api";
import { useRenderedPathname } from "@/lib/use-rendered-pathname";
import { useAuthStore } from "@/stores/useAuthStore";

const PUBLIC_PATHS = ["/login", "/unauthorized"];

function SessionLoadingScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background text-sm text-muted-foreground">
      Loading session...
    </div>
  );
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const pathname = useRenderedPathname();
  const status = useAuthStore((s) => s.status);
  const user = useAuthStore((s) => s.user);
  const bootstrap = useAuthStore((s) => s.bootstrap);

  const isPublicPath = PUBLIC_PATHS.includes(pathname);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  let redirectTo: string | null = null;
  if (status === "authenticated" && user) {
    if (pathname === "/login") {
      redirectTo = defaultRouteForRole(user.role);
    } else if (!isPublicPath && !canAccessPath(user.role, pathname)) {
      redirectTo = "/unauthorized";
    }
  } else if (status === "anonymous" && !isPublicPath) {
    redirectTo = "/login";
  }

  useEffect(() => {
    if (!redirectTo) return;
    void navigate({ to: redirectTo, replace: true });
  }, [redirectTo, navigate]);

  if (status === "initializing") return <SessionLoadingScreen />;

  if (redirectTo) return <SessionLoadingScreen />;

  if (!isPublicPath && status !== "authenticated") return <SessionLoadingScreen />;

  return <>{children}</>;
}
