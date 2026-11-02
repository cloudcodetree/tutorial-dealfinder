"""A small FastAPI service exposing DealFinder over HTTP (Part 1).

Part 1 serves three things: a liveness check, the course lab, and the frozen
snapshot with its brand audit. Later parts add search, ranking and accounts to
this same app.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse

from .ingest import dedup_key

app = FastAPI(title="DealFinder")


@app.get("/healthz")
@app.get("/health")
def healthz():
    """Liveness: the process answers. Never touches the database.

    /health is the same check under a path Cloud Run serves: its front end
    reserves /healthz and answers it with Google's own 404."""
    return {"status": "ok"}


_LAB = Path(__file__).parent / "static" / "lab"
# The only files /lab/{name} serves. Anything else is a 404, so no path reaches the package.
LAB_ASSETS = {"lab.css": "text/css", "lab.js": "text/javascript", "lessons.json": "application/json"}


@app.get("/lab", response_class=HTMLResponse)
@app.get("/lab/", response_class=HTMLResponse)
def lab(request: Request) -> HTMLResponse:
    """The course lab, wired to the real endpoints.

    Behind the deals Worker the backend sits under /api, so the page gets that base when
    the request carries the edge header. Served directly on :8000 the base is empty."""
    html = (_LAB / "index.html").read_text()
    base = "/api" if "x-dealfinder-edge" in request.headers else ""
    html = html.replace('<meta name="api-base" content="">', f'<meta name="api-base" content="{base}">', 1)
    return HTMLResponse(html)


@app.get("/lab/{name}")
def lab_asset(name: str) -> Response:
    if name not in LAB_ASSETS:
        raise HTTPException(404, "not found")
    return Response((_LAB / name).read_bytes(), media_type=LAB_ASSETS[name])


# The retailer tokens Part 1's brand audit looks for (tests/test_part01.py pins the count).
_RETAILER_TOKENS = ("Walmart", "Target", "Costco", "Macy", "Best Buy", "Amazon", "mountainlifestyle", "kohl")


@app.get("/snapshot")
def snapshot_audit(q: str = "", limit: Annotated[int, Query(ge=1, le=500)] = 50):
    """Part 1's frozen snapshot, with the brand audit made visible: each row's raw
    `brand` field beside the brand extracted from its title. `retailer_polluted`
    counts rows whose raw brand is a retailer. `q` filters titles, case-insensitive."""
    from .features import title_brand
    from .snapshot import load_snapshot, to_products

    items = load_snapshot()
    polluted = sum(1 for x in items if any(t.lower() in (x.get("brand") or "").lower() for t in _RETAILER_TOKENS))
    needle = q.strip().lower()
    rows = []
    for item, p in zip(items, to_products(items)):
        if needle and needle not in p.title.lower():
            continue
        rows.append({"id": p.id, "title": p.title, "raw_brand": item.get("brand"), "brand": title_brand(p.title),
                     "price": p.price, "source": p.source, "dedup_key": dedup_key(p)})
        if len(rows) >= limit:
            break
    return {"total": len(items), "retailer_polluted": polluted, "count": len(rows), "rows": rows}
