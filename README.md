# DealFinder — Data Layer

Companion code for **[cloudcodetree.com/tutorials/dealfinder-data-layer](https://cloudcodetree.com/tutorials/dealfinder-data-layer/)** — Part 1 of the *DealFinder — AI Engineering* series.

Ingest messy product/price data from a **dataset**, a **live API**, and a **scraper** — all behind one `DealSource` interface — then normalize, dedup, and store it. This is the foundation everything else (search, ML, agent) is built on.

## Run it

**In a devcontainer / Codespaces (recommended — Python 3.11):** open the folder and let `.devcontainer/` set up. Or locally:

```bash
git clone https://github.com/cloudcodetree/tutorial-dealfinder && cd tutorial-dealfinder
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                          # 9 passed
python -m dealfinder.run_ingest    # ingested 2 products -> dealfinder.sqlite
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

`main` is the finished version.
