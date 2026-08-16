# DealFinder — Cost & Teardown

**The promise:** you can take the whole course and run DealFinder for **$0**. Every
path that *could* cost money is **opt-in**, **priced here before you enable it**, and
**tear-down-able** when you're done. This file is the single place that lays all of
that out — and the runbook to get back to $0.

> TL;DR — do nothing special and you pay nothing. To *guarantee* $0 after you finish:
> `docker compose down -v && colima stop` (details in [Teardown](#teardown)).

---

## Tier 0 — Running the course: $0, by default

Nothing here bills you. This isn't a promise, it's how the code is wired:

| What | Why it's free | Where it's enforced |
|---|---|---|
| **LLM calls** | Default model tier is **free-only** (`:free` OpenRouter models). With **no** `OPENROUTER_API_KEY` set, the app degrades to deterministic logic — no LLM at all. | `dealfinder/llm.py` (`models()` returns `:free` tier; `available()` gates on the key) |
| **Live sources** | Works on keyless/free tiers alone (iTunes keyless, eBay official API, RapidAPI/BestBuy free tiers), and falls back to the frozen snapshot with **zero** keys. | `dealfinder/live_sources.py`, `aggregate.py` |
| **Paid sources stay OFF** | Apify, Amazon, Firecrawl are `metered=True` and require **both** an API key **and** `DEALFINDER_ENABLE_PAID_SOURCES=1`. Neither is set by default. | `live_sources.py` `_paid_ok()` |
| **Database & compute** | Local pgvector + FastAPI + Vite in Docker Compose on your machine. No cloud, no bill. | `docker-compose.yml` |

**Optional free-tier keys** (still $0): `RAPIDAPI_KEY`, `BESTBUY_API_KEY`, eBay creds, and
`OPENROUTER_API_KEY` *with the default free model tier* all stay within free allowances.
They add live breadth but don't move you off $0 — the app runs fine without any of them.

---

## Tier 1 — Opt-in paid surfaces (only if you deliberately turn them on)

Each requires an explicit action. None is on by default.

| Surface | Turn it ON with | Cost | Turn it OFF |
|---|---|---|---|
| **Apify** (Google-Shopping actor) | `APIFY_TOKEN` **and** `DEALFINDER_ENABLE_PAID_SOURCES=1` | pay-per-event credits | remove the flag / token |
| **Amazon** (Apify `junglee` actor) | same as Apify | **14-day trial, then ~$40+/mo** (no free Amazon path) | remove the flag / token + cancel the actor rental |
| **Firecrawl** (broad-web) | `FIRECRAWL_API_KEY` **and** `DEALFINDER_ENABLE_PAID_SOURCES=1` | free credits, then paid | remove the flag / key |
| **Higher-quality LLM** | `OPENROUTER_MODELS=<a paid model>` (with `OPENROUTER_API_KEY`) | per-token | unset `OPENROUTER_MODELS` → back to the free tier |

**Rule of thumb:** if `DEALFINDER_ENABLE_PAID_SOURCES` is unset and `OPENROUTER_MODELS`
is unset, no source or model can bill you — regardless of which keys are in `.env`.

---

## Tier 2 — Going *live* as a real product (beyond the course)

The consumer roadmap (`ROADMAP.md`) deploys to the cloud, which introduces **ongoing**
costs. This is deliberately separate from the course: **you never need any of it to
learn.** When you do deploy, each piece has a free tier or a clear price *and* a
teardown step:

| Component | Typical free tier | Paid when… | Teardown |
|---|---|---|---|
| Managed Postgres/pgvector (e.g. Supabase) | free project tier | you exceed free limits | delete the project |
| Cache (Redis) | small free instances | larger/managed | delete the instance |
| Hosting/CDN (e.g. Cloudflare Workers/Pages) | generous free tier | high traffic | delete the Worker/Pages project |
| Email (price-drop alerts) | free dev tier | volume | remove the API key / provider |
| Stripe (billing) | **test mode is free** | live mode processes real charges | stay in test mode; it never bills |

Treat "deploy to the cloud" as a Tier-1-style decision: enable one component at a time,
note its free-tier ceiling, and add its teardown line to your own checklist.

---

## Teardown

### A. Back to $0 locally (the common case — you finished the course)
```bash
cd companions/dealfinder
docker compose down -v                     # stop + delete containers AND volumes (pgdata, model_cache)
# if you ever used the full-ML profile, include its file so its containers go too:
docker compose -f docker-compose.yml -f docker-compose.full.yml down -v
colima stop                                # stop the Docker VM (reclaims RAM/CPU)
# to reclaim the VM's disk entirely (only if DealFinder is the only stack on it):
colima delete
```
`down -v` deletes the local database and the cached embedding model — intended when
you're done. Omit `-v` if you want to keep your local data but stop the containers.

> ⚠️ If you run **other** Docker stacks on the same Colima VM, use `docker compose down -v`
> (project-scoped) and **do not** `colima delete` — that would wipe the other stacks too.

### B. Disarm every paid surface (guarantee nothing can bill)
1. In `.env`, remove/blank: `DEALFINDER_ENABLE_PAID_SOURCES`, `APIFY_TOKEN`,
   `FIRECRAWL_API_KEY`, and any `OPENROUTER_MODELS` override.
2. **Revoke the keys at the source** (belt-and-suspenders): delete/rotate the tokens in
   the Apify, Firecrawl, and OpenRouter dashboards so a stray copy can't be used.
3. **Cancel rentals/subscriptions**: the Apify Amazon (`junglee`) actor and any Firecrawl
   plan — removing the key stops *use*, but cancel the plan to stop *recurring* charges.

### C. Decommission a cloud deployment (only if you deployed Tier 2)
Delete, per component: the Supabase project, the Redis instance, the Cloudflare
Worker/Pages project, the email provider key. Then confirm no provider dashboard shows a
running/billable resource.

### Partial teardown
- **Keep learning free, drop the paid extras:** do step **B** only — the local free
  stack keeps working.
- **Shrink the local footprint:** stop using the full-ML profile; the light default image
  is smaller (`docker compose up` without the `-f docker-compose.full.yml` override).

---

## Verify you're at $0

- `docker ps` → no DealFinder containers running.
- `colima status` → stopped (or the VM deleted).
- `env | grep -E 'DEALFINDER_ENABLE_PAID_SOURCES|APIFY_TOKEN|FIRECRAWL_API_KEY|OPENROUTER_MODELS'`
  → empty.
- `python scripts/cost_check.py` → reports **"no paid surfaces armed"** (see below).

A quick preflight — [`scripts/cost_check.py`](scripts/cost_check.py) — reports which paid
surfaces (if any) are currently armed by your environment, so "am I about to spend money?"
is answerable in one command, before you run anything.
