import { createServerFn } from "@tanstack/react-start";

/**
 * Total download count across every published release asset.
 *
 * Three deliberate choices:
 *
 * 1. **A server function, not a browser fetch.** If this ran client-side, every
 *    visitor's browser would make a request to api.github.com, which hands
 *    GitHub their IP and referrer. On a site whose entire argument is that it
 *    does not send your data to third parties, quietly doing that to read a
 *    vanity number would be indefensible.
 * 2. **Returns null rather than 0 on failure.** There is no published release
 *    yet, GitHub's unauthenticated API is rate limited to 60 requests an hour per
 *    IP, and networks fail. A confident "0 downloads" is worse than no counter,
 *    so null means "say nothing" and the UI renders nothing at all.
 * 3. **Cached in module scope.** A Vercel function instance handles many
 *    requests, and one API call per page view would exhaust the rate limit at
 *    trivial traffic and then start showing null to real visitors.
 */

const REPO = "wheretostudio/casper-flow";
const TTL_MS = 30 * 60 * 1000;

type Cache = { at: number; value: number | null };
let cache: Cache | null = null;

type Asset = { download_count?: number };
type Release = { draft?: boolean; assets?: Array<Asset> };

async function fetchCount(): Promise<number | null> {
  try {
    const res = await fetch(`https://api.github.com/repos/${REPO}/releases?per_page=100`, {
      headers: {
        Accept: "application/vnd.github+json",
        "User-Agent": "casper-flow-website",
      },
      signal: AbortSignal.timeout(4000),
    });
    if (!res.ok) return null;

    const releases = (await res.json()) as Array<Release>;
    if (!Array.isArray(releases) || releases.length === 0) return null;

    let total = 0;
    for (const release of releases) {
      if (release.draft) continue;
      for (const asset of release.assets ?? []) {
        total += asset.download_count ?? 0;
      }
    }
    // Zero across real releases still means "nothing worth showing".
    return total > 0 ? total : null;
  } catch {
    return null;
  }
}

export const getDownloadCount = createServerFn({ method: "GET" }).handler(
  async (): Promise<number | null> => {
    if (cache && Date.now() - cache.at < TTL_MS) return cache.value;
    const value = await fetchCount();
    cache = { at: Date.now(), value };
    return value;
  },
);

/** `12,481`, or `12.5k` once it stops fitting comfortably. */
export function formatCount(n: number): string {
  if (n < 10_000) return n.toLocaleString("en-US");
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 100_000 ? 1 : 0)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}
