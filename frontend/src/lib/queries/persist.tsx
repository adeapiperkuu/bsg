import { useMemo, type ReactNode } from "react";
import { useQueryClient, type Query } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";

import { useAuthStore } from "@/stores/useAuthStore";

/**
 * Persists a small allowlist of dashboard queries to localStorage so a reload paints the
 * last-known Operational Tower immediately instead of waiting on the (slow) endpoint, then
 * revalidates in the background.
 *
 * Two constraints shape this:
 *
 * 1. Per-user storage key. A persisted cache outlives the session, and `logout` does not
 *    clear the React Query cache. Without a per-user key, signing in as a different user on
 *    the same browser would restore — and instantly render — the previous user's portfolio.
 *    Keying by user id means another user's entry is never read; it is not a substitute for
 *    the server's own scoping, just a guard against showing the wrong cached org.
 *
 * 2. Allowlist, not everything. Only the dashboard payloads below are persisted. The rest of
 *    the app's queries (admin lists, knowledge documents, conversations) would bloat
 *    localStorage and put more personal data at rest in the browser for no gain.
 */

/** Bump when a persisted payload's shape changes, so stale entries are discarded. */
const CACHE_VERSION = "v1";

/**
 * How long a persisted entry may still be restored. This is a risk dashboard: an entry older
 * than this is dropped rather than shown, so a long-closed tab cannot reopen onto a
 * stale-but-plausible portfolio. Fresher entries are shown immediately and always carry the
 * "Updated ..." stamp the dashboard renders, so instant is never mistaken for current.
 */
const MAX_AGE_MS = 6 * 60 * 60 * 1000;

/** Query keys allowed into localStorage, matched on prefix. */
const PERSISTED_KEY_PREFIXES: readonly (readonly string[])[] = [
  ["dashboard", "operational-tower"],
  ["dashboard", "executive-summary"],
];

function isPersisted(query: Query): boolean {
  const key = query.queryKey;
  return PERSISTED_KEY_PREFIXES.some(
    (prefix) => prefix.length <= key.length && prefix.every((part, i) => key[i] === part),
  );
}

function PersistedCache({ userId, children }: { userId: string; children: ReactNode }) {
  const queryClient = useQueryClient();

  const persistOptions = useMemo(
    () => ({
      persister: createSyncStoragePersister({
        storage: window.localStorage,
        key: `bsg-query-cache:${CACHE_VERSION}:${userId}`,
      }),
      maxAge: MAX_AGE_MS,
      buster: CACHE_VERSION,
      dehydrateOptions: {
        // Only persist successful data; a persisted error would replay as a broken
        // dashboard on next load rather than simply refetching.
        shouldDehydrateQuery: (query: Query) =>
          query.state.status === "success" && isPersisted(query),
      },
    }),
    [userId],
  );

  return (
    <PersistQueryClientProvider
      // Remounting on user change rebuilds the persister against the new key and prevents
      // the outgoing user's restored entries from lingering in memory.
      key={userId}
      client={queryClient}
      persistOptions={persistOptions}
    >
      {children}
    </PersistQueryClientProvider>
  );
}

/**
 * Enables cache persistence for the signed-in user. Renders children untouched during SSR
 * (no localStorage) and while no user is resolved, so the login screen never persists.
 */
export function QueryPersistence({ children }: { children: ReactNode }) {
  const userId = useAuthStore((s) => s.user?.id);

  if (typeof window === "undefined" || !userId) return <>{children}</>;

  return <PersistedCache userId={userId}>{children}</PersistedCache>;
}
