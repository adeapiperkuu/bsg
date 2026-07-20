import { useRouterState } from "@tanstack/react-router";

export function useRenderedPathname(): string {
  return useRouterState({
    select: (s) => normalize(s.matches[s.matches.length - 1]?.pathname ?? s.location.pathname),
  });
}

function normalize(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
}
