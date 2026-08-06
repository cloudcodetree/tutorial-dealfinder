"""A small FastAPI service exposing DealFinder over HTTP.

Real endpoints, testable with FastAPI's TestClient (no server needed). The
production concerns — streaming, batching, quantized/vLLM serving, caching — are
discussed in the tutorial; this is the shape they hang off.
"""
from __future__ import annotations

import json
import os
import statistics
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from . import pgstore
from .aggregate import aggregate
from .auth import User, require_user
from .deal import deal_score
from .dealscore import fair_price
from .features import featurize
from .ingest import dedup_key
from .live_sources import LIVE_SOURCES
from .rag import _category_models, _load_medians
from .tools import load_catalog

app = FastAPI(title="DealFinder")

# Persistence is optional: if DATABASE_URL points at a reachable pgvector, we
# persist + enable semantic search; otherwise the app still does live search.
_DB = bool(os.getenv("DATABASE_URL"))
if _DB:
    try:
        pgstore.migrate()
    except Exception:
        _DB = False


def _embed_texts(texts):
    from .embed import embed_texts
    return embed_texts(texts)

_catalog = load_catalog()
_idx = {p.id: i for i, p in enumerate(_catalog)}
# Fair price uses the SAME per-category models as search/RAG (Part 3's audio model
# pins the hero-cast fair prices, e.g. Anker $108.33), so /deal agrees with the
# verdict badges and the tutorials — not a divergent global model.
_cat_models = _category_models(_catalog)
_fair = {
    p.id: float(fair_price(_cat_models[p.category], featurize(p)))
    if p.category in _cat_models else float(p.price)
    for p in _catalog
}
# Per-item same-query capture median (for the median signal in /deal badges).
_medians = _load_medians()


@app.get("/healthz")
def healthz():
    return {"status": "ok", "products": len(_catalog)}


@app.get("/search")
def search(q: str):
    """Aggregate live deals across sources; persist + embed them when a DB is set."""
    result = aggregate(q)
    if _DB and result["results"]:
        try:
            texts = [f"{r['title']} {r.get('brand') or ''}".strip() for r in result["results"]]
            pgstore.upsert(result["results"], _embed_texts(texts), query=q)
            result["persisted"] = pgstore.count()
        except Exception:
            pass
    return result


def _sse(event: str | None, data: dict) -> str:
    """Format one Server-Sent Event frame."""
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {json.dumps(data)}\n\n"


def _stream_search(query: str, sources):
    """Yield SSE frames: one `results` event per source that responds, then a
    terminal `done` event with the deduped/ranked view.

    This is the streaming twin of `aggregate()` for the Part 31 web front end:
    the browser paints offers as each source lands instead of blocking on the
    slowest one. It degrades gracefully — sources that are unconfigured or throw
    are simply skipped, so it still streams from whatever is live (or the
    snapshot-backed stub in tests).
    """
    seen: dict[str, object] = {}
    for src in sources:
        try:
            if not src.available():
                continue
            found = src.search(query) or []
        except Exception:
            # a flaky/rate-limited source never breaks the stream
            yield _sse("source_error", {"source": getattr(src, "name", "?")})
            continue
        if not found:
            continue
        batch = []
        for p in found:
            k = dedup_key(p)
            if k not in seen or p.price < seen[k].price:
                seen[k] = p
            batch.append({"id": p.id, "title": p.title, "price": p.price,
                          "source": p.source, "url": p.url, "image_url": p.image_url})
        yield _sse("results", {"source": getattr(src, "name", "?"), "results": batch})

    items = list(seen.values())
    median = round(statistics.median([p.price for p in items]), 2) if items else 0.0
    yield _sse("done", {"query": query, "count": len(items), "median_price": median})


@app.get("/search/stream")
def search_stream(q: str):
    """Stream live search results as Server-Sent Events (Part 31 backend).

    `text/event-stream`: emits one `results` event per responding source as the
    aggregator produces them, then a final `done` event. Reuses the same live
    sources as `/search`; runs live with the learner's own source keys, and
    still streams from whatever sources are available offline."""
    return StreamingResponse(
        _stream_search(q, LIVE_SOURCES),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/semantic")
def semantic(q: str, k: int = 12):
    """Search by meaning.

    With a database, searches everything ever aggregated (pgvector). Without one,
    it falls back to in-memory value-reranked retrieval over the frozen snapshot —
    so meaning-search works fully offline, the same way ``/ask`` does. Each result
    carries its two-signal deal verdict so the UI can badge DEAL/SUSPICIOUS."""
    if _DB:
        rows = pgstore.semantic_search(_embed_texts([q])[0], k=k)
        for r in rows:
            r["similarity"] = round(float(r["similarity"]), 3)
        return {"query": q, "count": len(rows), "results": rows, "backend": "pgvector"}

    # Offline fallback: the Part 5 retriever over the snapshot (Part 15's `retrieve`).
    from .rag import retrieve

    results = []
    for it in retrieve(q, k=k):
        p = _catalog[_idx[it.id]] if it.id in _idx else None
        results.append({
            "id": it.id, "title": it.title, "price": it.price, "source": it.source,
            "verdict": it.verdict, "pct_under_median": round(it.median_signal * 100),
            "reason": it.reason,
            "url": getattr(p, "url", None), "image_url": getattr(p, "image_url", None),
        })
    return {"query": q, "count": len(results), "results": results, "backend": "snapshot"}


@app.get("/ask")
def ask(q: str, k: int = 5):
    """RAG: retrieve real listings for the query, then GENERATE a grounded answer.

    Returns the `RagAnswer` — the synthesized answer, the retrieved item ids it
    used as `sources`, whether it passed the faithfulness check (`grounded`), and
    whether an LLM produced it (`used_llm`). With no OPENROUTER_API_KEY the
    deterministic extractive path answers, so this route works fully offline."""
    from .rag import answer as rag_answer

    a = rag_answer(q, k=k)
    return {
        "query": q,
        "answer": a.answer,
        "sources": a.sources,
        "grounded": a.grounded,
        "used_llm": a.used_llm,
    }


@app.get("/ask_agentic")
def ask_agentic(q: str, max_hops: int = 3):
    """Agentic RAG: retrieve → judge sufficiency → reformulate & retry → answer.

    Unlike `/ask` (one retrieval), the agent re-queries when the evidence is weak.
    Returns the grounded answer plus the full `hops` trajectory — each hop's query,
    the gate's verdict, and why — so the reasoning is inspectable. Fully offline:
    the sufficiency gate and the corpus-mined reformulator are deterministic."""
    from .agentic_rag import agentic_answer

    a = agentic_answer(q, max_hops=max_hops)
    return {
        "query": q,
        "answer": a.answer,
        "grounded": a.grounded,
        "used_llm": a.used_llm,
        "sources": a.sources,
        "hops": [
            {"query": h.query, "sufficient": h.sufficient, "reason": h.reason, "verdicts": h.verdicts}
            for h in a.hops
        ],
    }


class _TrapWriter:
    """A demo writer fooled by a too-good-to-be-true price — recommends the $46
    Bose QC45 trap as 'best value'. Used only by /review?trap=true to make the
    reviewer's catch visible; production writers are real LLMs."""

    def available(self) -> bool:
        return True

    def chat(self, messages, temperature: float = 0) -> str:
        return ("Best value: Bose QuietComfort 45 Wireless Noise Cancelling "
                "Headphones at $46.00 — an incredible deal.")


@app.get("/review")
def review_multiagent(q: str, k: int = 5, trap: bool = False):
    """Multi-agent writer/reviewer (Part 17): make the second opinion visible.

    A writer drafts a recommendation; an isolated reviewer re-retrieves the evidence
    and adversarially checks it (grounded? lead a real DEAL? trap warned?). If the
    draft is rejected, the orchestrator revises to the guaranteed-grounded
    deterministic answer. Pass ``trap=true`` to inject a writer fooled by the $46
    Bose trap and watch the reviewer catch it. Fully offline."""
    from . import orchestrate as orch
    from . import rag as _rag

    # Pin retrieval to the reproducible snapshot (orchestrate's contract) so the
    # writer/reviewer trail is stable regardless of any attached DATABASE_URL.
    writer = _TrapWriter() if trap else None
    draft = orch.recommend(q, k=k, llm=writer)
    draft_review = orch.review(q, draft, k=k)
    if draft_review.approved:
        final, revised, final_review = draft.answer, False, draft_review
    else:
        fixed = _rag.deterministic_answer(q, k=k, use_db=False)
        final_review = orch.review(q, fixed, k=k)
        final, revised = fixed.answer, True

    def _rv(r):
        return {"approved": r.approved, "issues": r.issues, "checks": r.checks}

    return {
        "query": q,
        "draft": {"answer": draft.answer, "used_llm": draft.used_llm},
        "draft_review": _rv(draft_review),
        "revised": revised,
        "final": final,
        "final_review": _rv(final_review),
    }


@app.get("/context")
def context_window(q: str, budget: int = 256, k: int = 20):
    """Context engineering (Part 16): make the window's packing *visible*.

    Retrieve wide (k), then pack the ranked deals into a token `budget` and reorder
    the survivors so the strongest sit at the edges ("lost in the middle"). Returns
    the real bge token math — the full retrieved block cost, the packed cost, what
    was kept vs evicted, and each survivor's position — so the "context as RAM"
    move is inspectable in the browser, not just asserted. Fully offline."""
    from . import context as ctx
    from . import rag as _rag

    # Pin to the reproducible snapshot path: the token math this surface teaches
    # must not vary with how much has been seeded into pgvector.
    items = _rag.retrieve(q, k=k, use_db=False)
    block_tokens = sum(ctx.count_tokens(_rag.build_context([it])) for it in items)
    packed = ctx.pack_deals(items, budget_tokens=budget)
    ordered = ctx.lost_in_the_middle(packed.included)

    def _pos(i: int, n: int) -> str:
        return "start" if i == 0 else "end" if i == n - 1 else "middle"

    n = len(ordered)
    return {
        "query": q,
        "budget": budget,
        "retrieved": len(items),
        "block_tokens": block_tokens,          # full k-block cost (does NOT fit)
        "packed_tokens": packed.tokens,        # what actually goes in the window
        "system_prompt_tokens": ctx.count_tokens(_rag._SYSTEM),
        "kept": len(packed.included),
        "evicted": len(packed.dropped),
        "included": [
            {"id": it.id, "title": it.title, "price": it.price, "source": it.source,
             "verdict": it.verdict, "pos": _pos(i, n)}
            for i, it in enumerate(ordered)
        ],
        "dropped": [
            {"id": it.id, "title": it.title, "price": it.price,
             "source": it.source, "verdict": it.verdict}
            for it in packed.dropped
        ],
    }


@app.get("/pipeline")
def pipeline_report():
    """Pipelines & orchestration (Part 20): run the 5-stage flow and show its trail.

    ingest → normalize → quality-gate → label → good_deals model. Runs the identical
    stage chain the Prefect flow wraps (FlowResult is the same either path) and
    returns each stage's outcome: the data-contract gate (rows valid/total, pass),
    the real label distribution, and the dbt-style good_deals count. Deterministic,
    offline. Reports whether the Prefect engine is installed."""
    from . import flows

    r = flows.snapshot_pipeline()   # identical FlowResult to the Prefect path; fast + quiet
    c = r.contract
    return {
        "has_prefect": flows.HAS_PREFECT,
        "stages": [
            {"name": "ingest", "detail": f"{r.ingested} rows from snapshot", "ok": True},
            {"name": "normalize", "detail": f"{r.normalized} rows · title-brand extracted", "ok": True},
            {"name": "quality-gate", "detail": f"{c.valid}/{c.total} valid · Pydantic contract", "ok": c.passed},
            {"name": "label", "detail": f"{r.labeled} rows · two-signal verdict", "ok": True},
            {"name": "good_deals model", "detail": f"{r.good_deals} rows · dbt-style SQL (10–90% band)", "ok": True},
        ],
        "contract": {"total": c.total, "valid": c.valid, "passed": c.passed,
                     "violations": c.violations[:5]},
        "label_distribution": r.label_distribution,
        "good_deals": r.good_deals,
    }


@app.get("/dataset")
def dataset_report():
    """Dataset engineering (Part 19): make the labeled training set inspectable.

    Builds the labeled dataset from the frozen snapshot and returns its real shape —
    the label distribution, the class imbalance + balanced class weights, and the
    leakage-safe grouped split (whole queries to one side). Query-independent: the
    training set is fixed. Deterministic and offline."""
    from . import dataset as ds_mod

    ds = ds_mod.build_labeled_dataset()
    summary = ds_mod.imbalance_summary(ds)
    tr, te = ds_mod.grouped_split(ds.queries, test_frac=0.25, seed=0)
    train_q = sorted({ds.queries[i] for i in tr})
    test_q = sorted({ds.queries[i] for i in te})
    return {
        "n_rows": int(ds.y.shape[0]),
        "n_features": int(ds.X.shape[1]),
        "feature_names": ds.feature_names,
        "n_queries": len(set(ds.queries)),
        "counts": summary["counts"],
        "fractions": summary["fractions"],
        "majority_class": summary["majority_class"],
        "majority_fraction": summary["majority_fraction"],
        "class_weights": summary["class_weights"],
        "strategy": summary["strategy"],
        "split": {
            "seed": 0, "test_frac": 0.25,
            "train_rows": len(tr), "test_rows": len(te),
            "train_queries": train_q, "test_queries": test_q,
            "disjoint": set(train_q).isdisjoint(test_q),
        },
    }


@app.get("/sources")
def sources():
    """Which live sources are configured right now."""
    return {s.name: s.available() for s in LIVE_SOURCES}


@app.get("/me")
def me(user: User = Depends(require_user)):
    """Demo protected route (Part 32). Returns the caller identity from their
    verified Supabase JWT. Auth is *opt-in* per route — the public search/deal
    routes above stay open; only routes that depend on `require_user` are gated.
    Runs live with the learner's own SUPABASE_JWT_SECRET."""
    return {"id": user.id, "email": user.email, "role": user.role}


@app.get("/", response_class=HTMLResponse)
def home():
    return (Path(__file__).parent / "static" / "index.html").read_text()


@app.get("/deal/{product_id}")
def deal(product_id: str):
    if product_id not in _idx:
        raise HTTPException(status_code=404, detail="unknown product")
    p = _catalog[_idx[product_id]]
    fair = _fair[p.id]
    from .dealscore import median_signal, residual_fraction, render_badge
    m = median_signal(p.price, _medians.get(p.id, 0.0))
    rf = residual_fraction(p.price, fair)
    return {
        "id": p.id, "title": p.title, "price": p.price,
        "fair": round(fair, 2),
        "deal_score": round(deal_score(p.price, fair), 3),
        "deal_pct": round(m, 3),
        "residual_frac": round(rf, 3),
        "badge": render_badge(m, rf),   # Part 18: the two-signal verdict as a UI badge
    }
