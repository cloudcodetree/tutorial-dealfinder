import { useCallback, useRef, useState } from "react";

// API base. Same-origin by default (the Vite dev proxy forwards /search & /me
// to the FastAPI backend on :8000); override with VITE_API_BASE in production.
export const API_BASE = import.meta.env.VITE_API_BASE ?? "";

// ---------------------------------------------------------------------------
// Wire shapes — mirror the real FastAPI backend (dealfinder/serve.py).
//
//   GET /search?q=            → { query, count, median_price, results: [...] }
//     result item: { id, title, brand, price, source, url, image_url, deal_pct }
//
//   GET /search/stream?q=     → text/event-stream:
//     event: results  data: { source, results: [{ id, title, price, source }] }
//     event: done     data: { query, count, median_price }
//     (event: source_error is emitted for a flaky source and simply skipped)
// ---------------------------------------------------------------------------

export interface Result {
  id: string;
  title: string;
  price: number;
  source: string;
  // Present on the /search JSON; the stream frames omit it, so it may be
  // undefined until we can derive it from the median in the `done` event.
  deal_pct?: number;
}

export interface SearchDone {
  query: string;
  count: number;
  median_price: number;
}

export interface SearchState {
  results: Result[];
  done: SearchDone | null;
  loading: boolean;
  error: string | null;
  // "sse" while streaming, "fetch" if we fell back to the plain JSON endpoint.
  transport: "sse" | "fetch" | null;
}

const EMPTY: SearchState = {
  results: [],
  done: null,
  loading: false,
  error: null,
  transport: null,
};

// deal_pct = how far below the median a price sits, as a percent (matches the
// backend's `(median - price) / median * 100`). Used to backfill deal_pct on
// streamed rows once we know the median, and to drive the DealBadge.
export function dealPctFromMedian(price: number, median: number): number {
  if (!median) return 0;
  return Math.round(((median - price) / median) * 1000) / 10;
}

/**
 * useSearch — subscribes to GET /search/stream via EventSource and renders
 * results incrementally as `results` frames arrive; reads count + median from
 * the terminal `done` event. If EventSource errors before completing, it falls
 * back to a single GET /search fetch.
 */
export function useSearch() {
  const [state, setState] = useState<SearchState>(EMPTY);
  const esRef = useRef<EventSource | null>(null);
  const doneRef = useRef(false);

  const close = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
  }, []);

  const fallbackFetch = useCallback(async (query: string) => {
    try {
      const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(query)}`);
      if (!res.ok) throw new Error(`search failed: ${res.status}`);
      const data = await res.json();
      const results: Result[] = (data.results ?? []).map((r: Result) => ({
        id: r.id,
        title: r.title,
        price: r.price,
        source: r.source,
        deal_pct: r.deal_pct,
      }));
      setState({
        results,
        done: { query: data.query, count: data.count, median_price: data.median_price },
        loading: false,
        error: null,
        transport: "fetch",
      });
    } catch (err) {
      setState((s) => ({
        ...s,
        loading: false,
        error: err instanceof Error ? err.message : String(err),
      }));
    }
  }, []);

  const search = useCallback(
    (query: string) => {
      const q = query.trim();
      if (!q) return;
      close();
      doneRef.current = false;
      setState({ ...EMPTY, loading: true, transport: "sse" });

      // EventSource isn't available in every environment (or may be disabled);
      // go straight to the fetch fallback if so.
      if (typeof EventSource === "undefined") {
        setState((s) => ({ ...s, transport: "fetch" }));
        void fallbackFetch(q);
        return;
      }

      const es = new EventSource(`${API_BASE}/search/stream?q=${encodeURIComponent(q)}`);
      esRef.current = es;

      es.addEventListener("results", (ev) => {
        const payload = JSON.parse((ev as MessageEvent).data) as { results: Result[] };
        const incoming = payload.results ?? [];
        setState((s) => {
          const seen = new Set(s.results.map((r) => r.id));
          const merged = [...s.results];
          for (const r of incoming) {
            if (!seen.has(r.id)) {
              seen.add(r.id);
              merged.push(r);
            }
          }
          return { ...s, results: merged };
        });
      });

      es.addEventListener("done", (ev) => {
        doneRef.current = true;
        const done = JSON.parse((ev as MessageEvent).data) as SearchDone;
        setState((s) => ({
          ...s,
          // Backfill deal_pct on streamed rows now that we know the median, and
          // re-rank cheapest-first to match the backend's ordering.
          results: [...s.results]
            .map((r) => ({
              ...r,
              deal_pct: r.deal_pct ?? dealPctFromMedian(r.price, done.median_price),
            }))
            .sort((a, b) => a.price - b.price),
          done,
          loading: false,
          transport: "sse",
        }));
        close();
      });

      es.onerror = () => {
        close();
        // A terminal `done` closes the stream normally — only treat an error as
        // a real failure if we never finished, and then fall back to /search.
        if (!doneRef.current) {
          setState((s) => ({ ...s, transport: "fetch" }));
          void fallbackFetch(q);
        }
      };
    },
    [close, fallbackFetch],
  );

  const reset = useCallback(() => {
    close();
    setState(EMPTY);
  }, [close]);

  return { ...state, search, reset };
}

/** GET /me with a bearer token (Part 28). Returns { id, email, role }. */
export interface Me {
  id: string;
  email: string | null;
  role: string;
}

export async function fetchMe(accessToken: string): Promise<Me> {
  const res = await fetch(`${API_BASE}/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (res.status === 401) throw new Error("not authenticated");
  if (!res.ok) throw new Error(`/me failed: ${res.status}`);
  return (await res.json()) as Me;
}
