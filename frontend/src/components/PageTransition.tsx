import { useRouterState } from "@tanstack/react-router";
import { useEffect, useRef, type ReactNode } from "react";

import { cn } from "@/lib/utils";

type Props = {
  children: ReactNode;
  className?: string;
};

/**
 * Fade-up on route change without remounting `<Outlet />`.
 * A `key={pathname}` wrapper remounts the outlet and can leave the previous
 * page (e.g. Operational Tower) visible until a second navigation.
 */
export function PageTransition({ children, className }: Props) {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.classList.remove("page-enter");
    // Force reflow so the animation can restart on the same node.
    void el.offsetWidth;
    el.classList.add("page-enter");
  }, [pathname]);

  return (
    <div ref={ref} className={cn("page-enter", className)}>
      {children}
    </div>
  );
}
