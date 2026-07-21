import { QueryClient } from "@tanstack/react-query";
import { createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";
import { PageLoadingScreen } from "./components/bsg/PageLoadingScreen";

export const getRouter = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        refetchOnWindowFocus: false,
        retry: 1,
      },
    },
  });

  const router = createRouter({
    routeTree,
    context: { queryClient },
    scrollRestoration: true,
    defaultPreloadStaleTime: 0,
    // Routes are code-split, so on a tab switch the previous page stays
    // rendered while the next route's chunk loads. Without a pending
    // component the sidebar/header update to the new tab while stale
    // content remains visible. Show a loading screen instead.
    defaultPendingComponent: PageLoadingScreen,
    defaultPendingMs: 150,
    defaultPendingMinMs: 200,
  });

  return router;
};
