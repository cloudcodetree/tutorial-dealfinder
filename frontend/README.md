# DealFinder web front end (Part 27)

A small Vite + React + TypeScript SPA over the DealFinder FastAPI backend. It
streams live search results as they arrive and (optionally) signs the user in
with Supabase.

## What it does

- **Streaming search.** The search bar subscribes to `GET /search/stream?q=…`
  via `EventSource` and renders results **incrementally** — one batch per
  `results` frame, as each source responds — then shows the total **count** and
  **median** from the terminal `done` frame. If the stream errors before
  finishing, it **falls back** to a single `GET /search?q=…` fetch.
- **Deal badges.** Each offer is a `ResultCard` (title · source · `deal_pct` ·
  price) with a `DealBadge` using the four canonical badge tokens:
  **`DEAL` · `FAIR` · `SUSPICIOUS` · `OVERPRICED`** (see `src/components/DealBadge.tsx`).
  The stream frames carry `{id, title, price, source}`; `deal_pct` is filled in
  from the median once the `done` frame lands (the `/search` fallback returns
  `deal_pct` directly).
- **Auth (Supabase).** Sign in / session / sign out with `@supabase/supabase-js`.
  On an active session it calls the protected `GET /me` with the session's
  bearer token and shows the verified identity; a **pro** affordance is gated by
  the user's `role`.

## Configuration

Copy `.env.example` → `.env.local`:

| Var | Purpose |
| --- | --- |
| `VITE_API_BASE` | Backend origin. Blank in dev → uses the Vite proxy. |
| `VITE_SUPABASE_URL` | Your Supabase project URL (Project Settings → API). |
| `VITE_SUPABASE_ANON_KEY` | Your Supabase anon (public) key. |

Only `VITE_`-prefixed, **public** values belong here — the Supabase anon key is
public by design; never put a service-role key or the API's `SUPABASE_JWT_SECRET`
in the frontend.

## Run it

```bash
# 1. Start the backend (from the repo root) on :8000
uvicorn dealfinder.serve:app --reload

# 2. Start the SPA
cd frontend
npm install
npm run dev        # http://localhost:5173
```

The Vite dev server proxies `/search`, `/search/stream`, and `/me` to
`http://localhost:8000`, so `EventSource` and the bearer-token `/me` call work
same-origin without CORS.

### Live vs. anonymous

- **Public search works with no keys at all** — the backend streams from
  whatever sources are configured (offline it falls back to the keyless iTunes
  source), so you'll see cards stream in immediately.
- **Sign-in + `/me` + the pro gate need the learner's own Supabase project.**
  Set `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` here, and set the matching
  `SUPABASE_JWT_SECRET` on the backend (see `dealfinder/auth.py`). Without them,
  the Auth panel says auth is off and the app runs anonymously.

## Build

```bash
npm run build      # type-checks (tsc -b) then emits ./dist
```

`node_modules/` and `dist/` are gitignored.

## Layout

```
frontend/
├── index.html
├── vite.config.ts          # dev proxy → :8000
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api.ts              # useSearch (SSE) + /search fetch fallback + fetchMe
│   ├── lib/supabase.ts     # supabase-js client from VITE_ env
│   └── components/
│       ├── SearchBar.tsx
│       ├── ResultCard.tsx
│       ├── DealBadge.tsx   # the four §9.7 badge tokens
│       └── Auth.tsx
```
