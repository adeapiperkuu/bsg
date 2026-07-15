import { queryOptions } from "@tanstack/react-query";

import { listUsers } from "@/lib/api";
import { queryKeys, STALE_TIME_MS, USERS_GC_TIME_MS } from "@/lib/queries/keys";

/**
 * `/users` returns every visible user in one response; search, filtering, sorting
 * and pagination all run client-side, so this is fetched once and reused.
 */
export const usersQueryOptions = queryOptions({
  queryKey: queryKeys.users,
  queryFn: listUsers,
  staleTime: STALE_TIME_MS,
  gcTime: USERS_GC_TIME_MS,
});
