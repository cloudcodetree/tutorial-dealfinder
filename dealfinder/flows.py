"""Pipelines & orchestration (Part 20): a real, runnable Prefect flow that turns
the frozen snapshot into a labeled, quality-gated training table.

The DAG is the boring-but-hireable shape every batch ML pipeline has::

    ingest → normalize (title_brand) → contract (data-quality gate) → label → persist

Each stage is a plain function that does one job against the ONE committed
snapshot (spec §2), so the whole thing reproduces offline with no network. On top
of those functions we lay Prefect's orchestration — task retries, result caching,
and a flow that fails loud if the data contract is violated.

**Real vs anchored (be honest — this feeds a tutorial):**

- The stage functions, the Pydantic data contract, and the ``good_deals.sql``
  dbt-style model are **real and executed** — the tests run them end-to-end and
  pin the counts.
- Prefect is a genuine optional dependency (``pip install .[prefect]``). When it
  is installed the ``@flow``/``@task`` decorators are **real** — ``snapshot_flow``
  actually runs on a Prefect engine with retries + caching. When it is absent, we
  fall back to calling the same functions directly (``snapshot_pipeline``) and the
  decorators degrade to no-ops, so the DAG is still exercised. The tutorial states
  which path the reader is on.

Row counts this file produces against ``electronics-2026-07.json`` (270 rows):
  - contract: 270/270 rows valid (price>0, known category, required columns)
  - labeled:  270 rows → {deal: 71, fair: 40, suspicious: 32, overpriced: 127}
  - good_deals.sql view: 111 rows
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, field_validator

from .dataset import LabeledDataset, build_labeled_dataset
from .features import CATEGORY_CODES, title_brand
from .snapshot import load_snapshot

# The known category set the contract enforces (spec §4 — the 11 snapshot cats).
KNOWN_CATEGORIES: frozenset[str] = frozenset(CATEGORY_CODES)

# Columns every snapshot row must carry for the pipeline to trust it.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "id", "query", "category", "title", "price", "median_price_at_capture",
)

_MODEL_SQL = Path(__file__).resolve().parent / "models" / "good_deals.sql"


# ---------------------------------------------------------------------------
# The data contract — a Pydantic row schema + a whole-snapshot validation.
# ---------------------------------------------------------------------------
class SnapshotRow(BaseModel):
    """A validated snapshot row: the columns the pipeline depends on, checked.

    This is the "data contract" — the assertions a warehouse would enforce before
    letting rows into a model: required columns present, ``price > 0``, and the
    ``category`` in the known set (spec §4). A row that fails is a contract
    violation, not a silently-dropped mystery.
    """

    id: str
    query: str
    category: str
    title: str
    price: float
    median_price_at_capture: float

    @field_validator("price")
    @classmethod
    def _price_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("price must be > 0")
        return v

    @field_validator("category")
    @classmethod
    def _category_known(cls, v: str) -> str:
        if v not in KNOWN_CATEGORIES:
            raise ValueError(f"category {v!r} not in known set")
        return v


@dataclass
class ContractReport:
    """Outcome of validating a batch of rows against :class:`SnapshotRow`."""

    total: int
    valid: int
    violations: list[dict] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """The gate: the contract passes only when every row is valid."""
        return self.total > 0 and self.valid == self.total


class DataContractError(RuntimeError):
    """Raised when the data-quality gate rejects the batch (the flow fails)."""


def validate_contract(rows: list[dict]) -> ContractReport:
    """Validate every row against the contract; report totals + violations.

    Deterministic and offline. Reports the real counts (does not raise) so the
    flow can decide whether to gate — see :func:`quality_gate`.
    """
    violations: list[dict] = []
    valid = 0
    for r in rows:
        missing = [c for c in REQUIRED_COLUMNS if c not in r]
        if missing:
            violations.append({"id": r.get("id"), "error": f"missing columns: {missing}"})
            continue
        try:
            SnapshotRow.model_validate(r)
            valid += 1
        except Exception as exc:  # pydantic ValidationError → one violation record
            violations.append({"id": r.get("id"), "error": str(exc).splitlines()[0]})
    return ContractReport(total=len(rows), valid=valid, violations=violations)


# ---------------------------------------------------------------------------
# The good_deals dbt-style model — run the committed .sql over the rows.
# ---------------------------------------------------------------------------
def run_good_deals_model(rows: list[dict]) -> list[dict]:
    """Materialize ``models/good_deals.sql`` over the snapshot rows (SQLite).

    Loads the rows into an in-memory table named ``products`` and runs the
    committed SQL — the same seam a warehouse/dbt run would use, but offline and
    stdlib-only. Returns the view rows (dicts).
    """
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE products (id TEXT, query TEXT, category TEXT, title TEXT, "
        "brand TEXT, price REAL, median_price_at_capture REAL)"
    )
    con.executemany(
        "INSERT INTO products VALUES (?,?,?,?,?,?,?)",
        [
            (
                r["id"], r["query"], r["category"], r["title"], r.get("brand"),
                float(r["price"]), float(r["median_price_at_capture"]),
            )
            for r in rows
        ],
    )
    try:
        result = [dict(row) for row in con.execute(_MODEL_SQL.read_text()).fetchall()]
    finally:
        con.close()
    return result


# ---------------------------------------------------------------------------
# The DAG stages — plain functions, one job each. Prefect wraps these below.
# ---------------------------------------------------------------------------
def ingest_snapshot(path: str | None = None) -> list[dict]:
    """Stage 1 — ingest: read the frozen snapshot rows (stands in for a connector)."""
    return load_snapshot(path)


def normalize_rows(rows: list[dict]) -> list[dict]:
    """Stage 2 — normalize: attach the TITLE-extracted true brand (spec §2).

    The raw ``brand`` field is the retailer in 154/270 rows; ``title_brand`` pulls
    the real manufacturer out of the title. We add it as ``true_brand`` without
    dropping the original, so the contract still sees every column.
    """
    return [{**r, "true_brand": title_brand(r["title"])} for r in rows]


def quality_gate(rows: list[dict]) -> ContractReport:
    """Stage 3 — the data-quality gate: enforce the contract or fail the flow.

    Runs :func:`validate_contract` and raises :class:`DataContractError` if any
    row is invalid. This is the "stop the pipeline before bad data reaches the
    model" seam.
    """
    report = validate_contract(rows)
    if not report.passed:
        raise DataContractError(
            f"contract failed: {report.valid}/{report.total} rows valid; "
            f"first violation: {report.violations[0] if report.violations else None}"
        )
    return report


def label_rows(path: str | None = None) -> LabeledDataset:
    """Stage 4 — label: build the two-signal labeled dataset (Part 19 reused)."""
    return build_labeled_dataset(path)


@dataclass
class FlowResult:
    """What the snapshot flow returns — the real, pinnable pipeline output."""

    ingested: int
    normalized: int
    contract: ContractReport
    labeled: int
    label_distribution: dict[str, int]
    good_deals: int
    persisted_to: str | None = None

    @property
    def gate_passed(self) -> bool:
        return self.contract.passed


def _run_pipeline(path: str | None, persist_dir: str | None) -> FlowResult:
    """The pure orchestration body, shared by the Prefect flow and the fallback."""
    rows = ingest_snapshot(path)
    normalized = normalize_rows(rows)
    report = quality_gate(normalized)  # raises on violation
    ds = label_rows(path)
    deals = run_good_deals_model(normalized)

    persisted_to: str | None = None
    if persist_dir is not None:
        out = Path(persist_dir)
        out.mkdir(parents=True, exist_ok=True)
        target = out / "good_deals.csv"
        lines = ["id,query,category,price,median_deal_pct"]
        lines += [
            f"{d['id']},{d['query']},{d['category']},{d['price']},{d['median_deal_pct']:.4f}"
            for d in deals
        ]
        target.write_text("\n".join(lines) + "\n")
        persisted_to = str(target)

    return FlowResult(
        ingested=len(rows),
        normalized=len(normalized),
        contract=report,
        labeled=int(ds.y.shape[0]),
        label_distribution=ds.label_distribution(),
        good_deals=len(deals),
        persisted_to=persisted_to,
    )


def snapshot_pipeline(path: str | None = None, persist_dir: str | None = None) -> FlowResult:
    """Run the DAG as plain functions — the always-available, Prefect-free path.

    Same stages, same output as :func:`snapshot_flow`; this is what runs (and what
    the tests exercise) when Prefect is not installed.
    """
    return _run_pipeline(path, persist_dir)


# ---------------------------------------------------------------------------
# Prefect orchestration — REAL when prefect is installed, no-op decorators when not.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - import guard; both branches are covered by their tests
    from prefect import flow, task
    from prefect.cache_policies import NO_CACHE

    HAS_PREFECT = True
except ImportError:  # pragma: no cover
    HAS_PREFECT = False

    def task(*dargs, **dkwargs):  # type: ignore[no-redef]
        """No-op stand-in for ``@task`` when Prefect isn't installed."""
        def wrap(fn):
            return fn
        return wrap(dargs[0]) if dargs and callable(dargs[0]) else wrap

    def flow(*dargs, **dkwargs):  # type: ignore[no-redef]
        """No-op stand-in for ``@flow`` when Prefect isn't installed."""
        def wrap(fn):
            return fn
        return wrap(dargs[0]) if dargs and callable(dargs[0]) else wrap


if HAS_PREFECT:
    # Real Prefect tasks: retries on the ingest connector (transient failures),
    # caching on the pure normalize step, and NO_CACHE on the gate so it always
    # re-checks. These decorators are live — the flow runs on a Prefect engine.
    _ingest_task = task(retries=2, retry_delay_seconds=1, cache_policy=NO_CACHE)(ingest_snapshot)
    _normalize_task = task(name="normalize")(normalize_rows)
    _gate_task = task(name="quality-gate", cache_policy=NO_CACHE)(quality_gate)
    _label_task = task(name="label", cache_policy=NO_CACHE)(label_rows)
    _model_task = task(name="good-deals-model")(run_good_deals_model)

    @flow(name="dealfinder-snapshot")
    def snapshot_flow(path: str | None = None, persist_dir: str | None = None) -> FlowResult:
        """The orchestrated snapshot pipeline (real Prefect flow).

        ingest → normalize → quality-gate → label → good_deals model → persist.
        The gate raises :class:`DataContractError`, which fails the flow run.
        """
        rows = _ingest_task(path)
        normalized = _normalize_task(rows)
        report = _gate_task(normalized)  # fails the flow on contract violation
        ds = _label_task(path)
        deals = _model_task(normalized)

        persisted_to: str | None = None
        if persist_dir is not None:
            out = Path(persist_dir)
            out.mkdir(parents=True, exist_ok=True)
            target = out / "good_deals.csv"
            lines = ["id,query,category,price,median_deal_pct"]
            lines += [
                f"{d['id']},{d['query']},{d['category']},{d['price']},{d['median_deal_pct']:.4f}"
                for d in deals
            ]
            target.write_text("\n".join(lines) + "\n")
            persisted_to = str(target)

        return FlowResult(
            ingested=len(rows),
            normalized=len(normalized),
            contract=report,
            labeled=int(ds.y.shape[0]),
            label_distribution=ds.label_distribution(),
            good_deals=len(deals),
            persisted_to=persisted_to,
        )
else:
    # Prefect absent: the flow entrypoint is the plain-function DAG. Same signature.
    snapshot_flow = snapshot_pipeline  # type: ignore[assignment]
