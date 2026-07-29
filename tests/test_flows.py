"""Pipelines & orchestration (Part 20) over the frozen snapshot.

Deterministic and offline. The load-bearing assertions run the whole DAG
(ingest → normalize → data-quality gate → label → good_deals model) end-to-end
and pin the REAL output counts, plus prove the contract gate rejects bad rows.

If Prefect is installed the real ``@flow`` is exercised; if not, the same DAG is
run through the plain-function fallback (``snapshot_pipeline``) — either way the
pinned numbers must match.
"""
import pytest

from dealfinder.flows import (
    HAS_PREFECT,
    ContractReport,
    DataContractError,
    quality_gate,
    run_good_deals_model,
    snapshot_flow,
    snapshot_pipeline,
    validate_contract,
)
from dealfinder.snapshot import load_snapshot

# Real, pinned pipeline output over electronics-2026-07.json (270 rows).
EXPECTED_DISTRIBUTION = {"deal": 71, "fair": 40, "suspicious": 32, "overpriced": 127}
EXPECTED_GOOD_DEALS = 111


def test_contract_passes_on_the_real_snapshot():
    # Every one of the 270 committed rows satisfies the data contract: required
    # columns present, price > 0, category in the known set.
    rows = load_snapshot()
    report = validate_contract(rows)
    assert isinstance(report, ContractReport)
    assert report.total == 270
    assert report.valid == 270
    assert report.passed
    assert report.violations == []


def test_contract_flags_bad_rows_and_gate_raises():
    rows = load_snapshot()
    bad = [
        dict(rows[0]),                       # valid
        {**rows[1], "price": -5.0},          # price <= 0
        {**rows[2], "category": "nonsense"}, # unknown category
        {k: v for k, v in rows[3].items() if k != "price"},  # missing column
    ]
    report = validate_contract(bad)
    assert report.total == 4
    assert report.valid == 1
    assert not report.passed
    assert len(report.violations) == 3
    # The gate turns a failed contract into a flow-stopping error.
    with pytest.raises(DataContractError):
        quality_gate(bad)


def test_good_deals_model_row_count_is_pinned():
    # The committed dbt-style good_deals.sql, run over the snapshot via SQLite,
    # yields exactly 111 honest deals (10%–90% under the same-query median).
    rows = load_snapshot()
    deals = run_good_deals_model(rows)
    assert len(deals) == EXPECTED_GOOD_DEALS
    # Every surfaced deal is inside the discount band and priced positively.
    for d in deals:
        assert d["price"] > 0
        assert 0.10 <= d["median_deal_pct"] <= 0.90


def test_plain_pipeline_end_to_end_pins_real_output():
    # The Prefect-free DAG always runs; pin its real output.
    result = snapshot_pipeline()
    assert result.ingested == 270
    assert result.normalized == 270
    assert result.gate_passed
    assert result.labeled == 270
    assert result.label_distribution == EXPECTED_DISTRIBUTION
    assert result.good_deals == EXPECTED_GOOD_DEALS


def test_normalize_attaches_title_extracted_brand():
    # The pipeline's normalize stage derives the true brand from the title,
    # distinct from the retailer-polluted raw brand field.
    from dealfinder.flows import normalize_rows

    rows = normalize_rows(load_snapshot())
    assert all("true_brand" in r for r in rows)
    # The hero Anker deal: title_brand extracts a real manufacturer from the
    # title (it resolves to the sub-brand "Soundcore" here), distinct from the
    # retailer that pollutes the raw brand field.
    anker = next(r for r in rows if "Anker Soundcore Q20i" in r["title"])
    assert anker["true_brand"] == "Soundcore"


def test_persist_writes_good_deals_csv(tmp_path):
    result = snapshot_pipeline(persist_dir=str(tmp_path))
    assert result.persisted_to is not None
    written = tmp_path / "good_deals.csv"
    assert written.exists()
    # header + one line per good deal.
    lines = written.read_text().strip().splitlines()
    assert lines[0] == "id,query,category,price,median_deal_pct"
    assert len(lines) - 1 == EXPECTED_GOOD_DEALS


@pytest.mark.skipif(not HAS_PREFECT, reason="Prefect not installed; plain DAG covered above")
def test_prefect_flow_runs_end_to_end():
    # The real @flow on a Prefect engine returns the same pinned output.
    result = snapshot_flow()
    assert result.ingested == 270
    assert result.gate_passed
    assert result.labeled == 270
    assert result.label_distribution == EXPECTED_DISTRIBUTION
    assert result.good_deals == EXPECTED_GOOD_DEALS
