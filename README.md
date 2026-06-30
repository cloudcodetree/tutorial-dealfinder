# DealFinder — companion code

Companion code for the **[DealFinder — AI Engineering](https://cloudcodetree.com/tutorials/)** tutorial series on cloudcodetree.com. One repo, built up **version by version** — each step is a git tag, and `main` is the finished version.

- **Part 1 — [Build the Data Layer](https://cloudcodetree.com/tutorials/dealfinder-data-layer/)**: ingest messy product/price data from a **dataset**, a **live API**, and a **scraper** behind one `DealSource` interface; normalize, dedup, and store it.
- **Part 3 — ["Is it a good deal?" price model](https://cloudcodetree.com/tutorials/dealfinder-deal-model/)**: learn a fair price from features with a from-scratch linear model, evaluate it, and flag underpriced listings.
- **Part 4 — [Recommender](https://cloudcodetree.com/tutorials/dealfinder-recommender/)**: content-based + collaborative filtering, scored offline with precision@k and NDCG.
- **Part 5 — [Semantic search](https://cloudcodetree.com/tutorials/dealfinder-search/)**: real neural embeddings (fastembed) + BM25, fused with RRF, then reranked by value.
- **Part 6 — [Structured extraction](https://cloudcodetree.com/tutorials/dealfinder-extraction/)**: messy listing → schema-validated JSON (Pydantic), deterministic offline + an LLM path.
- **Part 8 — [The agent](https://cloudcodetree.com/tutorials/dealfinder-agent/)**: a ReAct loop over tools (text-to-SQL + deal ranking), with a human-in-the-loop gate.
- **Part 9 — [MCP server](https://cloudcodetree.com/tutorials/dealfinder-mcp/)**: expose the tools over the Model Context Protocol — callable from Claude Code.
- **Part 10 — [Safety & governance](https://cloudcodetree.com/tutorials/dealfinder-safety/)**: prompt-injection detection, PII redaction, output validation, audit log.

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
```

Work through it **version by version** — each step is a git tag:

```bash
git checkout step-02   # then step-03, step-04, …
```

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

`main` is the finished version.
