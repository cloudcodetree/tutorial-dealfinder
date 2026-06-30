# DealFinder — companion code

Companion code for the **[DealFinder — AI Engineering](https://cloudcodetree.com/tutorials/)** tutorial series on cloudcodetree.com. One repo, built up **version by version** — each step is a git tag, and `main` is the finished version.

- **Part 1 — [Build the Data Layer](https://cloudcodetree.com/tutorials/dealfinder-data-layer/)**: ingest messy product/price data from a **dataset**, a **live API**, and a **scraper** behind one `DealSource` interface; normalize, dedup, and store it.
- **Part 3 — ["Is it a good deal?" price model](https://cloudcodetree.com/tutorials/dealfinder-deal-model/)**: learn a fair price from features with a from-scratch linear model, evaluate it, and flag underpriced listings.
- **Part 4 — [Recommender](https://cloudcodetree.com/tutorials/dealfinder-recommender/)**: content-based + collaborative filtering, scored offline with precision@k and NDCG.

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

`main` is the finished version.
