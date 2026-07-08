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
from .dealmodel import LinearModel
from .features import feature_matrix
from .ingest import dedup_key
from .live_sources import LIVE_SOURCES
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
_X = feature_matrix(_catalog)
_model = LinearModel().fit(_X, [p.price for p in _catalog])
_fair = {p.id: float(fp) for p, fp in zip(_catalog, _model.predict(_X))}


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

    This is the streaming twin of `aggregate()` for the Part 27 web front end:
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
            batch.append({"id": p.id, "title": p.title, "price": p.price, "source": p.source})
        yield _sse("results", {"source": getattr(src, "name", "?"), "results": batch})

    items = list(seen.values())
    median = round(statistics.median([p.price for p in items]), 2) if items else 0.0
    yield _sse("done", {"query": query, "count": len(items), "median_price": median})


@app.get("/search/stream")
def search_stream(q: str):
    """Stream live search results as Server-Sent Events (Part 27 backend).

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
    """Search everything ever aggregated, by meaning (pgvector)."""
    if not _DB:
        raise HTTPException(status_code=503, detail="no database configured")
    rows = pgstore.semantic_search(_embed_texts([q])[0], k=k)
    for r in rows:
        r["similarity"] = round(float(r["similarity"]), 3)
    return {"query": q, "count": len(rows), "results": rows}


@app.get("/sources")
def sources():
    """Which live sources are configured right now."""
    return {s.name: s.available() for s in LIVE_SOURCES}


@app.get("/me")
def me(user: User = Depends(require_user)):
    """Demo protected route (Part 28). Returns the caller identity from their
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
    return {
        "id": p.id, "title": p.title, "price": p.price,
        "fair": round(_fair[p.id], 2),
        "deal_score": round(deal_score(p.price, _fair[p.id]), 3),
    }
