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
| **Live sources** | Each source needs its own free key (Best Buy, eBay, RapidAPI; iTunes is keyless). Without keys, `/search` can return no results: it has no snapshot fallback. Production runs Best Buy only (`DEALFINDER_SOURCES=BestBuy`), inside its free 50,000 calls a day. | `dealfinder/live_sources.py`, `aggregate.py` |
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

## Tier 3 — the live product (deals.beta.cloudcodetree.com until launch)

The real deployment, separate from the course: you never need it to learn. It is
designed to cost **$0 a month**, and every component below has a free allowance, a
way the design stays under it, and a teardown command. At launch there is no Best
Buy key, so there are no scheduled jobs and no stored store data (Plan 3, "Launch
without Best Buy").

| Component | Free allowance (source) | Expected use | How we stay under | Teardown |
|---|---|---|---|---|
| Cloud Run service `dealfinder-api` | 180,000 vCPU-s, 360,000 GB-s and 2M requests a month ([GCP free tier](https://docs.cloud.google.com/free/docs/free-cloud-features)) | well under 1% at launch traffic | scales to zero, `max_instance_count = 2`, request-based billing (`cpu_idle = true`), 30 s timeout. The price of scaling to zero is a cold start: median 7.2 s, worst 9.8 s over 3 runs on 2026-10-31 (`RUNBOOK.md` §8) | `tofu -chdir=deploy/gcp destroy` |
| Cloud Scheduler | 3 jobs per **billing account** ([pricing](https://cloud.google.com/scheduler/pricing)) | not used at launch | no job exists until a Best Buy key arrives; `cost_check --live` counts jobs across the billing account | none to remove |
| Secret Manager `dealfinder-env` | 6 active versions, 10,000 accesses a month ([GCP free tier](https://docs.cloud.google.com/free/docs/free-cloud-features)) | 1 version, one access per instance start | `deploy/secrets.py` destroys older versions on every write | `tofu -chdir=deploy/gcp destroy` |
| Artifact Registry `dealfinder` | 0.5 GB storage ([GCP free tier](https://docs.cloud.google.com/free/docs/free-cloud-features)) | one image is 297 MB in the registry (297,449,999 bytes, measured 2026-10-31); two versions share the dependency and model layers | cleanup policy keeps the 2 newest images; `cost_check --live` fails above 450 MB | `tofu -chdir=deploy/gcp destroy` |
| Cloud Logging | 50 GiB per project a month ([GCP free tier](https://docs.cloud.google.com/free/docs/free-cloud-features)) | megabytes | one short JSON line per request | removed with the project |
| Budget alert | free | 1 budget at $1 | emails at 50%, 90%, 100% and a 100% forecast | `tofu -chdir=deploy/gcp destroy` |
| Workers `dealfinder-edge-staging` (beta host) and `dealfinder-edge` (no domain until launch) | 100,000 requests a day per account on Workers Free ([pricing](https://developers.cloudflare.com/workers/platform/pricing/)) | every page view and API call is one request | edge cache for anonymous search, rate limits on the LLM routes | `npx wrangler delete <name>` for each (in `edge/`) |
| Supabase `cct-demos` (shared with cloudcodetree.com) | 500 MB database on the free plan ([pricing](https://supabase.com/pricing)) | no visitor data at launch | own `dealfinder` schema; Best Buy rows purged before 72 hours once a key exists | `DROP ROLE dealfinder_svc` (see `RUNBOOK.md`) |
| Best Buy API | 50,000 calls a day, no billing | not used at launch | no key yet | none |
| Healthchecks.io | 20 checks on Hobbyist | not used at launch | Plan 5 adds the uptime check | none |

Check the live footprint any time:

```bash
python scripts/cost_check.py --live --project <project_id>   # every line ✓ and exit 0
```

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

### D. Decommission the live product (Tier 3)
```bash
tofu -chdir=deploy/gcp destroy -var-file=prod.tfvars   # Cloud Run, the secret, the registry, WIF, the budget
cd edge && npx wrangler delete dealfinder-edge-staging && npx wrangler delete dealfinder-edge   # the Workers and their custom domains
# then, as the database admin, in the shared project:
#   DROP ROLE dealfinder_svc;
```
Then run `python scripts/cost_check.py --live --project <project_id>`. It should fail
to find the service, which confirms nothing is left.

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
