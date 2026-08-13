import { createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";

/**
 * No QueryClient here, deliberately.
 *
 * This used to construct one and hand it down as route context, with a
 * QueryClientProvider wrapping the whole tree in __root.tsx - and nothing ever
 * called useQuery. The only data this site fetches is the download count, which a
 * TanStack Router loader gets on the server. So it was a client-side data-fetching
 * library, shipped to every visitor, doing nothing but adding to the bundle on a
 * site whose argument is that software should be light.
 *
 * Add it back when something actually needs client-side caching.
 */
export const getRouter = () => {
  return createRouter({
    routeTree,
    scrollRestoration: true,
    defaultPreloadStaleTime: 0,
  });
};
