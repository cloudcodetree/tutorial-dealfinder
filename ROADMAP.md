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

---

## The launch gate (must be TRUE before any public launch)

- [ ] Cost-per-query measured and bounded (no LLM on the default path; caching in front).
- [ ] Abuse/bot rate-limiting on anonymous endpoints.
- [ ] Async/horizontal: no single-worker blocking; heavy work off the request path.
- [ ] Observability: per-request latency + cost + error tracking, alerting.
- [ ] Privacy: GDPR/CCPA data-subject flows + cookie consent; secrets in a manager, not `.env`.
- [ ] Affiliate compliance (disclosure) if monetized.

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

**Done:** the AI value+trust layer (P4 core) and the per-user isolation primitive (P1 foundation).
**Next:** P1 — consumer accounts + watchlist + price-drop alerts.
