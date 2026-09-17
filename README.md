# DealFinder — companion code

Companion code for the **[Become a Full-Stack AI Engineer](https://cloudcodetree.com/tutorials/)** tutorial series on cloudcodetree.com. One repo, built up **version by version** — each step is a git tag, and `main` is the finished version.

The written course is **37 parts**, grouped into five phases. Each part links to its
lesson on cloudcodetree.com; the course is still being written, so lesson links go live
as parts are published.

- **Parts 1–9 — Data & the deal signal** ([start](https://cloudcodetree.com/tutorials/dealfinder-part-01/)): the `DealSource` interface, normalization and dedup over a frozen 270-item electronics snapshot, how LLMs actually work, a from-scratch price model, recommenders, semantic search, structured extraction, live connectors, responsible scraping, and tiered aggregation with a circuit breaker.
- **Parts 10–17 — LLM engineering** ([start](https://cloudcodetree.com/tutorials/dealfinder-part-10/)): QLoRA fine-tuning of the extractor, a ReAct agent over real tools, an MCP server, pgvector persistence, RAG and agentic RAG, context engineering, and the writer/reviewer multi-agent pattern.
- **Parts 18–24 — Product surface & ML operations** ([start](https://cloudcodetree.com/tutorials/dealfinder-part-18/)): the web app, dataset engineering (labeling, grouped splits, class imbalance), Prefect/dbt pipelines, ML & DL breadth, experiment tracking and a model registry, evaluation as a discipline, and closing the MLOps loop.
- **Parts 25–30 — Production engineering** ([start](https://cloudcodetree.com/tutorials/dealfinder-part-25/)): safety, security and governance; serving it fast and cheap; real inference optimization; containers; cloud and Kubernetes; observability, cost and ops.
- **Parts 31–37 — SaaS & shipping** ([start](https://cloudcodetree.com/tutorials/dealfinder-part-31/)): the React front end, auth and accounts, saved searches and a suggestions worker, payments and SaaS mechanics, security and compliance at scale, operating the real system, and a closing case study + system-design interview.

The code below is built in **38 tagged steps** — finer-grained than the parts, so one
lesson may span several tags. The full step table is at the bottom of this README.

## Cost & footprint — free and frugal by default

Running DealFinder for the whole course costs **$0** and fits a **modest laptop**. Both
budgets — money and machine — are bounded by default, visible before they bite, and
reclaimable when you're done:

- **Cost:** free-only LLM tier (degrades to deterministic with no key), keyless/free sources
  + snapshot fallback, paid sources off unless you set `DEALFINDER_ENABLE_PAID_SOURCES=1`.
  Full policy + teardown → **[COST.md](COST.md)**.
- **Disk/RAM:** light default image, opt-in full-ML profile, download-once model cache, and a
  bounded VM. Footprint + reclaim runbook → **[RESOURCES.md](RESOURCES.md)**.

Check both before you run anything:

```bash
python scripts/cost_check.py      # "no paid surfaces armed — you're at $0", or a priced warning
python scripts/disk_check.py      # host/VM headroom; warns before a heavy build fills the disk
```

## Run it

**In a devcontainer / Codespaces (recommended — Python 3.11):** open the folder and let `.devcontainer/` set up. Or locally:

```bash
git clone https://github.com/cloudcodetree/tutorial-dealfinder && cd tutorial-dealfinder
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                          # 17 passed
python -m dealfinder.run_ingest    # ingested 2 products -> dealfinder.sqlite
python data/make_catalog.py        # wrote 28 tents -> data/sample/catalog.json
python -m dealfinder.train_model   # MAE, R^2, and the deals it finds
uvicorn dealfinder.serve:app --port 8000   # the live aggregator web app → http://localhost:8000
```

Work through it **version by version** — each step is a git tag:

```bash
git checkout step-02   # then step-03, step-04, …
```

## Run the whole stack in one command (Docker Compose)

For a transportable dev environment — no host Python/Node/pnpm, just Docker —
`docker-compose.yml` brings up the three services together with live reload:

| Service    | URL                     | What it is                                   |
|------------|-------------------------|----------------------------------------------|
| `db`       | `localhost:5434`        | Postgres + pgvector (named volume `pgdata`)  |
| `backend`  | http://localhost:8000   | FastAPI aggregator + all `/endpoint` inspectors (`uvicorn --reload`) |
| `frontend` | http://localhost:5173   | Vite + React SPA (HMR; proxies the API to `backend`) |

```bash
cp .env.example .env                    # optional: add live-source / Supabase / Stripe keys
docker compose up                       # start db + backend + frontend
docker compose --profile seed up seed   # one-shot: populate pgvector from the 270-item snapshot
docker compose down                     # stop  (add -v to also delete the pgvector volume)
```

- **Live editing:** `./dealfinder` and `./frontend` are bind-mounted — edit a `.py`
  and uvicorn reloads; edit a `.tsx` and Vite hot-swaps it. No rebuild.
- **No keys needed:** without `.env`, live search falls back to the frozen snapshot
  and the auth/billing inspectors use throwaway demo secrets. Add keys to `.env`
  (and set `DEALFINDER_ENABLE_PAID_SOURCES=1`) to hit live sources.
- **"By meaning" search:** empty pgvector falls back to snapshot retrieval; run the
  `seed` profile once to populate it with real embeddings.
- This supersedes running `uvicorn` / `vite` / a standalone pgvector container by hand.
- No `docker compose` plugin? The standalone `docker-compose <same args>` binary works too.
- **Memory & the ML endpoints:** most of the app (`/healthz`, search, RAG,
  `/context`, and the `/auth` `/billing` `/compliance` `/ops` `/evals`
  `/suggestions` inspectors, the SPA, the `seed` profile) runs fine on a small
  (~2 GB) Docker VM from the **light default image**. Three endpoints need the
  heavy extras: `/models` (needs `torch`), `/tracking` (needs `mlflow`), and
  `/pipeline`'s `has_prefect` (needs `prefect`) — `Dockerfile.dev` omits them on
  purpose so the image and the Docker-VM disk stay small. For those, opt into the
  **full-ML override**:

  ```bash
  docker compose -f docker-compose.yml -f docker-compose.full.yml up
  ```

  It swaps the backend to `Dockerfile.full` (the extras) and wants the Docker VM
  at ≥ 4 GB (`colima start --memory 4`) — fitting the torch MLP OOMs a 2 GB VM.
  (Or run those three in the host venv:
  `pip install -e ".[dev,torch,mlflow,prefect]"` then `uvicorn dealfinder.serve:app`.)
  The embed model is cached in the `model_cache` volume, so it downloads once and
  survives rebuilds. *Live* semantic search also wants ≥ 4 GB (it loads that model).

## Steps (and what each adds)

| Step | What you add |
|---|---|
| `step-01` | Package scaffold + tooling + devcontainer |
| `step-02` | `Product` common schema (pydantic) |
| `step-03` | `DealSource` protocol + dataset connector |
| `step-04` | Live-API connector (httpx; mocked in tests) |
| `step-05` | Scraper connector (selectolax; fixture-parsed) |
| `step-06` | Ingest + cross-source dedup |
| `step-07` | SQLite store + one-command pipeline |
| `step-08` | Feature engineering (`features.py`) |
| `step-09` | Linear model from scratch — normal equation (`dealmodel.py`) |
| `step-10` | Deal scoring (`deal.py`) |
| `step-11` | Synthetic catalog with a known price function (`make_catalog.py`) |
| `step-12` | Train + evaluate + surface deals (`train_model.py`) |
| `step-13` | Recommenders — content-based + item-item CF (`recommend.py`) |
| `step-14` | Ranking metrics — precision@k, recall@k, NDCG (`ranking.py`) |
| `step-15` | Synthetic likes with latent personas (`make_interactions.py`) |
| `step-16` | Recommend + offline eval vs popularity (`run_recs.py`) |
| `step-17` | Search primitives — cosine, BM25, RRF, value rerank (`search.py`) |
| `step-18` | Neural embeddings on CPU via fastembed (`embed.py`) |
| `step-19` | Four-stage search demo (`run_search.py`) |
| `step-20` | Structured extraction — schema + rule/LLM paths (`extract.py`) |
| `step-21` | Extraction demo over messy listings (`run_extract.py`) |
| `step-22` | ReAct agent loop + tools (text-to-SQL) (`agent.py`, `tools.py`) |
| `step-23` | Tool-chaining agent demo (`run_agent.py`) |
| `step-24` | MCP server — tools, a resource, a prompt (`mcp_server.py`) |
| `step-25` | Guardrails — injection, PII, validation, audit (`safety.py`) |
| `step-26` | Evaluation harness — golden set, metrics, A/B, CI gate (`evals.py`) |
| `step-27` | FastAPI service + semantic cache (`serve.py`, `cache.py`) |
| `step-28` | Dockerfile + CI/CD + deploy config (`Dockerfile`, `ci.yml`) |
| `step-29` | Cost attribution + budget + drift (PSI) (`ops.py`) |
| `step-30` | **Live aggregator + web app** — real sources (iTunes/RapidAPI/Apify) (`live_sources.py`, `aggregate.py`, web UI) |
| `step-31` | **Terraform pgvector + persistence + semantic search** (`infra/`, `pgstore.py`, `/semantic`) |
| `step-32` | **Whole stack in Terraform (db+app) + semantic toggle in the web UI** |
| `step-33` | **Firecrawl broad-web source** (`FirecrawlSource`, review-domain filter) |
| `step-34` | **Tiered aggregation (anti-throttle)** — tier order, early-stop, circuit breaker |
| `step-35` | **OpenRouter LLM** — tiered models + graceful degrade; real Part-6 extraction (`llm.py`) |
| `step-36` | **eBay Browse API source** — official search, used+new, affiliate-ready (`EbaySource`) |
| `step-37` | **Shopify /products.json source** — keyless, low-risk niche retail (`ShopifySource`) |
| `step-38` | **Best Buy API source** + curated Shopify defaults (`BestBuySource`) |

`main` is the finished version.
