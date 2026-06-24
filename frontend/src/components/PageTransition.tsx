import { useRouterState } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type Props = {
  children: ReactNode;
  className?: string;
};

export function PageTransition({ children, className }: Props) {
  const pathname = useRouterState({ select: (state) => state.location.pathname });

  return (
    <div key={pathname} className={cn("page-enter", className)}>
      {children}
    </div>
  );
}
