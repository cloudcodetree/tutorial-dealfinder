# DealFinder — Consumer Product Roadmap

**What this is.** DealFinder is a **consumer SaaS** (B2C): a public web product that lets
anyone search for an item and get the best real deals across sources, ranked by value,
with an AI layer that **protects normal people from too-good-to-be-true (scam) listings**.
It is *software as a service* — just consumer-facing, not B2B. That distinction drives the
architecture: **per-user (not per-org), affiliate revenue (not seats), frictionless public
access (not login-gated)**, and cheap-per-query AI at public scale.

> Built in the course companion (`companions/dealfinder`) on the `draft/electronics-regen`
> branch; reconciled with the 37-part course later. Not published.

---

## Where we are (foundations already shipped)

- **Aggregation**: live multi-source search (`/search`), snapshot fallback, dedup.
- **The AI value+trust layer**: two-signal deal verdict (median signal + model residual),
  a **layered fair-price estimator** (trained per-category model → peer estimate → value-only)
  so *any* search — guitars, cookware — gets a real verdict, not just electronics (`/ranked`).
- **RAG** (grounded `/ask`), **semantic search** (`/semantic`, pgvector).
- **Per-user isolation primitive**: Postgres Row-Level Security, fail-closed, enforced via a
  non-superuser role (`tenancy.py` + `pgstore.py`). Built as "tenant"; **reframes cleanly to
  per-user** (`tenant_id` → `user_id`), with anonymous `public` search as the default.
- **UI**: Nocturne redesign (`/redesign`) — all modes wired to real endpoints.
- **Dev stack**: light-by-default Docker Compose + opt-in full-ML profile.

## Principles

1. **Frictionless first.** Anyone can search with zero signup. Accounts are optional, for
   personalization only.
2. **Cheap per query.** Public traffic is read-heavy and unpaid-per-use — cache hard, reuse
   embeddings, keep the LLM off the hot path. Cost-per-query is survival.
3. **Trust is the product.** "We flag the scams" is the headline, not a footnote.
4. **Enterprise-grade engineering, consumer product.** Reliability/observability/security/
   privacy at public scale — the "enterprise" bar applies to the *engineering*, not the buyer.
5. **The data compounds.** Every search grows the price knowledge base (the moat).
6. **Respect the operator's budget — money *and* machine — bounded, visible, reclaimable.**
   A learner runs the course for **$0** and on a **modest laptop**; both budgets are bounded
   by default, legible *before* they bite, and reclaimable on demand. Any paid path is opt-in,
   priced up front, and tear-down-able ([COST.md](COST.md), `scripts/cost_check.py`); the disk/
   RAM footprint is bounded, monitored, and prunable ([RESOURCES.md](RESOURCES.md),
   `scripts/disk_check.py`). New features must not break either guarantee, and anything that can
   spend money **or** balloon disk ships with its number and its teardown/reclaim step. These
   are hard constraints, not aspirations — the disk-full VM corruption we hit is exactly what
   ignoring the machine budget costs.

---

## The launch gate (must be TRUE before any public launch)

A box is checked only when every proof it names passes on `main`. Plan 8 checks them,
after the live proofs pass. Live commands name the launch host. Before launch, run them
against `https://deals.beta.cloudcodetree.com`.

- [ ] Cost-per-query measured and bounded (no LLM on the default path; caching in front). Proof: tests/test_observability.py::test_llm_usage_comes_from_the_response, tests/test_observability.py::test_missing_usage_is_null_not_guessed, tests/test_serve.py::test_anonymous_search_is_edge_cacheable_and_signed_in_is_private, tests/test_serve.py::test_ask_answers_are_cached_with_ttl, tests/test_serve.py::test_ask_daily_cap_falls_back_to_the_deterministic_path, tests/test_llm.py::test_openrouter_refused_in_production
- [ ] Abuse/bot rate-limiting on anonymous endpoints. Proof: tests/test_ratelimit.py::test_llm_routes_are_limited_hardest, tests/test_ratelimit.py::test_client_ip_header_is_trusted_only_behind_the_edge_secret, tests/test_ratelimit.py::test_a_flood_of_new_clients_cannot_evict_a_limited_one, tests/test_serve.py::test_ask_has_the_strictest_limit; live: the 31st `/api/search` in 10 s answers 429
- [ ] Heavy work in scheduled jobs, capped horizontal scaling, no queue at launch. There are no jobs at launch: they wait for a Best Buy key. Proof: tests/test_gcp_config.py::test_scales_to_zero_and_is_capped, tests/test_gcp_config.py::test_no_scheduled_jobs_at_launch; live: `gcloud run services describe dealfinder-api --region us-central1 --format='value(spec.template.metadata.annotations)'` shows maxScale 2
- [ ] Observability: per-request latency + cost + error tracking, alerting. Proof: tests/test_observability.py::test_request_log_carries_latency_and_cost, tests/test_observability.py::test_request_log_has_no_query_text, tests/test_observability.py::test_sentry_scrubs_query_string, tests/test_observability.py::test_call_rate_warning_fires_once, tests/test_healthchecks_setup.py::test_setup_creates_the_uptime_check_idempotently (and edge/src/uptime.test.ts); live: the Plan 5 Task 14 drills
- [ ] Privacy: data-subject export and delete over the real tables; cookie consent required only if a non-essential cookie is ever added, none at launch; secrets in a manager, not `.env`. Proof: tests/test_account.py::test_delete_account_removes_only_own_rows, tests/test_account.py::test_export_returns_every_table, tests/test_account.py::test_no_backend_route_sets_cookies, tests/test_settings.py::test_production_never_reads_dotenv, tests/test_runbook.py::test_cloud_run_request_logs_are_excluded; live: `python scripts/cookie_audit.py https://deals.cloudcodetree.com`, and after one `/api/check` request `gcloud logging read 'log_name:"run.googleapis.com%2Frequests"' --freshness=10m --limit=1 --project dealfinder-prod-cct` prints nothing (the request-log exclusion is applied)
- [ ] Every deployed component's ongoing cost is documented in COST.md with a teardown step; `scripts/cost_check.py` (extended for cloud) reports the live billable footprint. Proof: tests/test_cost_check.py::test_live_report_passes_a_healthy_footprint, tests/test_cost_check.py::test_live_report_flags_a_missing_budget_and_a_big_registry, tests/test_runbook.py::test_cost_rows_cover_the_new_free_services; live: `python scripts/cost_check.py --live --project dealfinder-prod-cct`
---

## Phases (sequenced by dependency + value)

### P1 — Consumer core: identity, saved searches, watchlist, alerts
**Goal:** turn isolated search into a product people return to.
- Reframe tenancy → **per-user**: `user_id` from consumer auth (Supabase email/Google/Apple);
  anonymous stays `public`. RLS scopes each user's private data.
- New tables + endpoints: `saved_searches`, `watchlist` (item + target price), `search_history`.
- **Price-drop alerts**: a background job re-checks watchlist prices and notifies (email first).
- UI: sign-in (optional), "save this search", "watch this item", a watchlist view.
**Decisions:** email-only vs social login first; alert channel (email vs push).
**DoD:** anonymous search unchanged; a logged-in user saves/watches items, sees only their own
(RLS), and receives a price-drop alert; tests for per-user isolation + the alert job.

**Progress (2026-08-15):**
- [x] Per-user isolation primitive (RLS keyed on `user_id`; `userstore.py`).
- [x] **Watchlist** — add/list/remove (`/watchlist`), `hit` flag when last price ≤ target;
      per-user private (RLS), account-gated (`require_account`), dev `X-User-Id` sign-in.
- [x] Watchlist **UI** in the Nocturne surface (＋watch on deals, watchlist view, count badge).
- [x] Real consumer auth (Supabase OAuth in the browser) — replace the dev `X-User-Id`.
      Proof: tests/test_auth.py::test_valid_token_returns_user, tests/test_auth.py::test_hs256_token_is_rejected,
      tests/test_auth.py::test_jwks_unreachable_fails_closed.
- [x] Saved searches (parallel to watchlist). Proof: tests/test_userstore.py::test_saved_searches_private_per_user,
      tests/test_serve.py::test_saved_search_cap_is_409.
- [ ] Price-drop **alert delivery** (needs the P2 job queue: re-price watchlist → email/push).
      Deferred: waits for a Best Buy key (2026-10-27).

### P2 — Scale & cost-per-query
**Goal:** survive being popular without going broke.
- **Caching**: Redis for `/ranked` + `/semantic` results and query embeddings (TTL); CDN for
  static + deal pages. Confirm the **LLM is never on the default search path**.
- **Async + job queue** (Arq/Celery): embeddings, price re-checks, alerts off the request path;
  kill the single-worker fragility (multiple workers/pods).
- **Rate limiting / bot protection** on anonymous endpoints.
**Decisions:** Redis vs in-proc + CDN; queue choice.
**DoD:** measured cost-per-query + p95 latency with cache hit/miss; load test; alerts run async.

### P3 — Monetization: affiliate click-through
Deferred: revenue skipped (owner decision, 2026-10-25).

**Goal:** make it a business the B2C way.
- Wrap outbound "open offer" links with **affiliate tags** (Amazon Associates, eBay Partner
  Network, etc.); **click + conversion tracking**; revenue attribution.
- Required **affiliate disclosure** UI.
**Decisions:** which networks first; server-side redirect (trackable) vs client tag.
**DoD:** every outbound click is attributed; a revenue report; disclosure shown.

### P4 — Trust as the headline
**Goal:** make scam-protection the core promise (mostly surfacing what exists).
- Elevate the two-signal verdict in UI + copy for normal users ("why we held this back");
  confidence/explanation; a "safety" explainer page.
**DoD:** the verdict is the primary visual; plain-language explanations; user comprehension check.

### P5 — Growth: SEO & shareability
**Goal:** organic discovery (a consumer product lives on it).
- **Server-rendered, indexable deal pages** with `schema.org/Product`; sitemaps; shareable deal
  URLs + Open Graph images; canonical/meta.
**DoD:** deal pages render server-side, validate as rich results, are crawlable + shareable.

### P6 — Reliability, observability, security, privacy (continuous; a launch gate)
**Goal:** the enterprise-grade engineering bar for a public product.
- OpenTelemetry tracing, metrics, error tracking; **LLM/AI cost+latency+quality per request**.
- Secrets manager (not `.env`), encryption; **GDPR/CCPA data-subject flows** + cookie consent
  (build on `/compliance`); dependency/SBOM scanning.
- CI/CD, staging→prod, IaC (`infra/`), backups/DR.
**DoD:** the launch-gate checklist is green.

### P7 — The AI moat: a live price knowledge base
**Goal:** long-term defensibility that compounds with usage.
- Ingest price data from **every** user search (crowd-sourced) into the historical store;
  **price-history tracking** per item (powers alerts *and* better fair prices).
- **Continuously (re)trained** per-category fair-price models; model registry → versioned
  serving; **eval-in-production** + user feedback (thumbs) on verdicts.
**DoD:** fair prices improve measurably as data grows; price-history charts; a retrain→eval→
promote loop wired to real (not frozen) data.

---

## Sequencing rationale

P1 makes it a **product**, P2 makes it **survivable**, P3 makes it a **business**, P5 makes it
**discoverable** — that's the path to a real public launch. P4 is cheap and can be folded into
P1's UI (the verdict already exists). P6 runs **continuously** and is the launch gate. P7 is the
**moat** — it compounds, so start feeding it early (P1/P2 already persist searches per user),
but the heavy model-serving/continuous-training work comes once there's traffic to learn from.

**Done:** the AI value+trust layer (P4 core); per-user isolation (RLS); **P1 watchlist**
(backend + UI + tests, per-user isolated, price-drop `hit` flag).
**Next in P1:** real Supabase OAuth (replace dev `X-User-Id`), saved searches, then P2's
job queue to power real price-drop **alert delivery** (re-price watchlist → email).
