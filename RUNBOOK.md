# DealFinder — Production Runbook

Operational reference for the DealFinder API + SPA (Part 32, "Ship & operate").
Every endpoint and module named below is real code in this repo. Numbers marked
**(anchored)** are measured on this machine and will differ in your environment —
re-measure with `scripts/loadtest.py` against your own deployment before you set
SLOs off them.

---

## 1. Service map

| Piece            | What it is                          | Where                                   |
|------------------|-------------------------------------|-----------------------------------------|
| API              | FastAPI app `DealFinder`            | `dealfinder/serve.py` (`app`)           |
| Aggregator       | tiered fan-out + circuit breaker    | `dealfinder/aggregate.py`               |
| Live sources     | eBay, RapidAPI, BestBuy, Apify, Shopify, Firecrawl, iTunes | `dealfinder/live_sources.py` (`LIVE_SOURCES`) |
| Auth             | Supabase-JWT verification           | `dealfinder/auth.py` (`require_user`)   |
| Billing / quota  | plans, metering, Stripe checkout    | `dealfinder/billing.py`                 |
| FinOps / drift   | cost tracker, budget, PSI           | `dealfinder/ops.py`                     |
| Persistence      | pgvector (optional)                 | `dealfinder/pgstore.py`                 |
| SPA              | Vite + React streaming search UI    | `frontend/`                             |
| IaC              | Docker/Terraform + K8s manifests    | `infra/main.tf`, `infra/k8s/`           |

Container listens on **:8000**. Config + secrets arrive as env (`DATABASE_URL`,
`SUPABASE_JWT_SECRET`, `RAPIDAPI_KEY`, `EBAY_APP_ID`/`EBAY_CERT_ID`,
`BESTBUY_API_KEY`, `APIFY_TOKEN`, `FIRECRAWL_API_KEY`, Stripe keys). Missing a
source key is *not* an outage — that source simply reports `available() == false`
and sits out (see `GET /sources`).

---

## 2. Health checks

| Check              | Command                                                        | Healthy response |
|--------------------|---------------------------------------------------------------|------------------|
| Liveness/readiness | `curl -fsS http://<host>:8000/healthz`                        | `{"status":"ok","products":<n>}` |
| Source status      | `curl -fsS http://<host>:8000/sources`                        | `{"eBay":true/false, ... }` — a map of configured sources |
| End-to-end search  | `curl -fsS 'http://<host>:8000/search?q=headphones'`          | envelope with `results`, `median_price`, `sources_live`, `throttled` |
| Deal detail        | `curl -fsS http://<host>:8000/deal/<product_id>`              | `{id,title,price,fair,deal_score}` (404 on unknown id) |
| Auth (if enabled)  | `curl -H "Authorization: Bearer <jwt>" http://<host>:8000/me` | `{id,email,role}` (401 without a valid JWT) |

`/healthz` is the probe wired into the K8s `readinessProbe`/`livenessProbe`
(`infra/k8s/deployment.yaml`) and Render `healthCheckPath` (`render.yaml`). It is
cheap and dependency-free — it does **not** touch live sources or the DB, so a
green `/healthz` with a failing `/search` means the app is up but a *source* or
the *DB* is degraded (see incidents below).

---

## 3. Key alerts

Set these against your metrics backend (the FinOps/drift signals come from
`dealfinder/ops.py`; wire `CostTracker`/`population_stability_index` into a
scheduled job or the request path).

| Alert                     | Signal / source                                             | Suggested threshold |
|---------------------------|-------------------------------------------------------------|---------------------|
| **Error rate**            | 5xx ratio on the API                                        | > 1% over 5 min → page |
| **p95 latency (/search)** | request latency histogram                                   | see baseline below; alert on 2× baseline sustained 10 min |
| **p95 latency (/healthz)**| request latency histogram                                   | > 250 ms sustained (probe should be single-digit ms) |
| **Source breaker trips**  | `throttled[]` in the `/search` envelope; benched sources in `aggregate._cooldown` | any source benched > 15 min, or ≥ half of `LIVE_SOURCES` benched at once |
| **Empty-result spike**    | share of `/search` responses with `count == 0`             | > 20% over 10 min (usually all real sources down → falling back to iTunes or empty) |
| **LLM cost / budget**     | `ops.CostTracker.total()` vs budget → `ops.budget_status(spent, budget)` returns `"warn"` (≥80%) / `"over"` (≥100%) | page on `"over"`, warn on `"warn"` |
| **Input drift (PSI)**     | `ops.population_stability_index(ref, cur)` / `ops.has_drifted(...)` (Part 20) | PSI ≥ 0.2 → trigger retrain review (rule of thumb in the code) |
| **Quota rejections**      | `billing.QuotaExceeded` raised in `meter_usage` → API returns 402/429 | sudden spike = pricing/limit misconfig or abuse |

### Latency baseline (anchored)

Measured with `scripts/loadtest.py` against a local `uvicorn` on this machine
(60 requests/endpoint, concurrency 6, live sources active). **Re-measure in your
environment — do not treat these as SLOs.**

| Endpoint    | p50      | p95       | p99       | throughput   | notes |
|-------------|----------|-----------|-----------|--------------|-------|
| `/healthz`  | 2.4 ms   | 136.6 ms  | 137.3 ms  | 346 req/s    | tail is cold-start jitter on first hits; steady-state is single-digit ms |
| `/search`   | 10.1 s   | 21.9 s    | 25.2 s    | 0.2 req/s    | dominated by **live source latency** (real network fan-out); 17/60 requests errored under concurrency as slow sources timed out |

Takeaway for alerting: `/healthz` is a fast probe; **`/search` is slow and
network-bound by design** (it calls real retailers). Do not put `/search` on a
tight-latency SLO — protect it with the circuit breaker, caching (`pgstore`
persistence + `/semantic`), and per-user quota instead. If `/search` p95 is
normally seconds, alert on *regressions* and on *error rate*, not an absolute ms.

---

## 4. Rollback

Artifact is a single container image (`Dockerfile`), deployed three ways — roll
back whichever you run:

**Kubernetes** (`infra/k8s/`, image `ghcr.io/cloudcodetree/dealfinder-app`):
```bash
kubectl -n dealfinder rollout undo deployment/dealfinder-app        # to previous
kubectl -n dealfinder rollout undo deployment/dealfinder-app --to-revision=<N>
kubectl -n dealfinder rollout status deployment/dealfinder-app      # watch it settle
```
Deployment runs `replicas: 2`; HPA scales 2→10 on 70% CPU (`infra/k8s/hpa.yaml`).
Pin the image by digest in `deployment.yaml` for deterministic rollbacks.

**Terraform / OpenTofu** (`infra/main.tf`): the app image is pinned in the stack;
to roll back, set the previous image tag/digest and `tofu apply`. Full teardown
is `tofu destroy`. The DB (pgvector) is a separate `docker_container` with a
named volume — **do not `destroy` if you need the persisted embeddings**.

**Render / PaaS** (`render.yaml`): redeploy the previous successful deploy from
the dashboard, or push the prior image tag. `healthCheckPath: /healthz` gates the
rollout, so a bad image that fails `/healthz` won't take traffic.

**Config-only rollback:** most "bad deploys" here are env/secret changes (a
rotated source key, a wrong `DATABASE_URL`). Revert the K8s `ConfigMap`/`Secret`
(`configmap.yaml` / `secret.example.yaml`) or the Terraform vars and restart —
no image change needed.

---

## 5. Common incidents

### A source throttles / errors
**Symptom:** the source appears in `throttled[]` in `/search` responses; results
thin out. **Cause & self-heal:** `aggregate.py`'s circuit breaker benches any
source that raises for `COOLDOWN_SECONDS` (90s) — it is *not* retried while
benched, so one flaky/rate-limited source never gets hammered and never sinks a
search (proven in `tests/test_chaos.py`). **Action:** usually none — it recovers
in ≤90s. If a source is *persistently* benched: check its key/quota, confirm
`GET /sources` shows it `available`, and inspect its provider dashboard for rate
limits. The tiered design means healthy lower-tier sources keep serving.

### All live sources down
**Symptom:** `/search` returns a well-formed **empty** envelope (`count: 0`,
`results: []`, `median_price: 0.0`) — **not** a 500 (pinned in
`tests/test_chaos.py::test_all_sources_down_returns_well_formed_empty_envelope`).
The SPA shows "No offers found," not an error banner. **Action:** check upstream
provider status and outbound network/egress; verify keys haven't all expired at
once. The keyless fallback (iTunes, `fallback_only`) and Shopify should keep at
least *something* live in most niches.

### Database down / unreachable
**Symptom:** `/healthz` and `/search` still return 200 (persistence is
*optional* — `serve.py` sets `_DB` false and swallows upsert errors), but
`/semantic` returns **503 "no database configured"** and search results stop
being persisted/embedded. **Action:** check `DATABASE_URL` and the pgvector
container/managed instance; `pgstore.migrate()` runs at startup, so a DB that
comes back needs no app change — new searches resume persisting. Restart the app
only if you want `_DB` re-evaluated immediately.

### LLM budget / cost exceeded
**Symptom:** `ops.budget_status(spent, budget)` returns `"over"`; cost dashboard
(`CostTracker.by_model()`) spikes. **Action:** identify the model driving spend
(`by_model()`), throttle or downgrade it, and confirm no runaway retry loop.
Budget is advisory in code — enforce it at the caller.

### Quota exceeded (user-facing)
**Symptom:** `billing.meter_usage` raises `QuotaExceeded`; API returns 402/429.
**Action:** expected for free-plan users past their `monthly_searches` — the SPA
should prompt an upgrade (`create_checkout_session`). A *broad* spike means a
misconfigured plan/limit or abuse; check `PLANS` and per-user metering.

### Model / data drift (Part 20)
**Symptom:** `ops.has_drifted(ref, cur)` true (PSI ≥ 0.2) — input distribution
moved. **Action:** open a retrain review; drift alone isn't an outage, but stale
`fair`/`deal_score` estimates degrade badge quality over time.

---

## 6. On-call first steps

1. **Triage in one command:** `curl -fsS http://<host>:8000/healthz` — up or down?
   - Down → app/infra issue → check pods (`kubectl -n dealfinder get pods`, logs),
     the last deploy, and roll back (§4) if it correlates with a release.
   - Up → it's a *dependency* (source, DB, quota, budget). Continue.
2. **Check sources:** `curl -fsS http://<host>:8000/sources` and run a probe
   search: `curl -fsS 'http://<host>:8000/search?q=headphones'` — read
   `sources_live[]` vs `throttled[]`. Map to §5.
3. **Check the DB:** hit `/semantic?q=test` — a 503 confirms DB/persistence is
   the degraded piece (search itself still works).
4. **Check cost/quota:** if the alert was FinOps, inspect `CostTracker` totals /
   `budget_status`; if user-facing 402/429, it's `billing` quota — likely
   working as intended.
5. **Decide:** self-healing (breaker cooldown, DB reconnect) → observe and
   confirm recovery. Release-correlated → roll back (§4). Provider outage →
   status-page it, lean on fallback sources, no code change.
6. **Repro locally** with the shipped tooling:
   - `.venv/bin/python -m pytest -q` — the offline suite incl.
     `tests/test_chaos.py` (graceful-degradation invariants).
   - `.venv/bin/python scripts/loadtest.py` — real latency against a running app
     (it refuses to run if `/healthz` is down, so it never invents numbers).
   - `cd frontend && npx playwright install chromium && npm run test:e2e` — SPA
     e2e (hermetic; badge taxonomy locked to the four §9 tokens).

---

## 7. Verification artifacts (Part 32)

| Artifact                      | What it proves                                             | Run |
|-------------------------------|-----------------------------------------------------------|-----|
| `frontend/e2e/*.spec.ts`      | SPA renders cards + §9 badges; empty query is safe        | `cd frontend && npm run test:e2e` (needs `npx playwright install chromium`) |
| `frontend/e2e/live.spec.ts`   | real full-stack search (opt-in)                           | backend on :8000, then `E2E_LIVE=1 npm run test:e2e:live` |
| `scripts/loadtest.py`         | real p50/p95/p99 + throughput, or refuses if app is down  | `.venv/bin/python scripts/loadtest.py` |
| `tests/test_chaos.py`         | breaker benches bad sources; all-down → empty, not 500    | part of `.venv/bin/python -m pytest -q` |
