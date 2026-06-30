"""A small FastAPI service exposing DealFinder over HTTP.

Real endpoints, testable with FastAPI's TestClient (no server needed). The
production concerns — streaming, batching, quantized/vLLM serving, caching — are
discussed in the tutorial; this is the shape they hang off.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .aggregate import aggregate
from .deal import deal_score
from .dealmodel import LinearModel
from .features import feature_matrix
from .live_sources import LIVE_SOURCES
from .tools import load_catalog

app = FastAPI(title="DealFinder")

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
    """Aggregate live deals for a query across every configured source."""
    return aggregate(q)


@app.get("/sources")
def sources():
    """Which live sources are configured right now."""
    return {s.name: s.available() for s in LIVE_SOURCES}


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
