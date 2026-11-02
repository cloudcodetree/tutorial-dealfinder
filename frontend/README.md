# DealFinder front end

The shopper page at `deals.beta.cloudcodetree.com` (the launch host later): **Check a deal**,
plus **How we rank** and **Privacy**. React 18 + Vite + TypeScript + react-router.
The course lab is not here: the backend serves it at `/lab` (`dealfinder/static/lab/`).

The browser never computes a verdict. It shows what `GET /api/check` returns: the
verdict badge (`DEAL`, `FAIR`, `SUSPICIOUS` or `OVERPRICED`) only when there is one,
the reason, and the model's fair price.

## Run it

```bash
# 1. the backend, from the repo root
.venv/bin/uvicorn dealfinder.serve:app --port 8000

# 2. the front end
cd frontend
npm ci
npm run dev -- --host 127.0.0.1      # http://127.0.0.1:5173
```

The app calls one path everywhere, the same-origin `/api`. In development Vite's proxy
sends `/api/*` to the backend with `/api` stripped (`vite.config.ts`). In production
the deals Worker (`edge/`) does the same. Point the proxy elsewhere with
`VITE_API_PROXY_TARGET=http://host:port npm run dev`. No keys are needed: sign-in
settings, when sign-in ships, come from the backend's `/config.json`.

## Build

```bash
npm run build      # tsc -b, then vite build → dist/
```

`dist/` is what the Worker serves as static assets. `public/robots.txt` keeps
crawlers off `/api/` and `/lab`.

## Tests

Playwright builds the app and serves `dist/` with `vite preview` on `:4173`. Run
`npx playwright install chromium` once.

| Mode | Command | Needs |
|---|---|---|
| Stubbed (default, what CI runs) | `npx playwright test` | nothing: `e2e/fixtures.ts` `stubApi` answers `/api/*` and blocks every other host |
| Live | `E2E_LIVE=1 npx playwright test e2e/live.spec.ts --project=desktop` | the backend on `:8000` |

Every spec runs twice: `desktop` and `mobile-375`. `e2e/a11y.spec.ts` runs axe
(WCAG 2.1 A and AA) on every page and checks that nothing scrolls sideways at
375 px, even with a 120-character unbroken product title. CI's `frontend` job runs
the stubbed suite and uploads `playwright-report/` when it fails.

## Layout

```
src/
  api.ts                 checkDeal, getConfig, ApiError: the only backend client
  App.tsx                routes: / and /check, /how-we-rank, /privacy, not found
  components/            Layout, CheckForm, VerdictBadge
  pages/                 CheckPage, ContentPage (renders src/content/*.md), NotFound
  content/               how-we-rank.md, privacy.md
  theme/                 tokens.css (the Nocturne tokens, AA verdict colors), base.css, layout.css, check.css
e2e/                     fixtures.ts, shell, check, pages, a11y, live specs
```
