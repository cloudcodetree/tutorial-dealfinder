"""Expose DealFinder as an MCP server — its tools become callable from any MCP
client (Claude Code, Claude Desktop, …).

Same capabilities you built in earlier parts, now behind the Model Context
Protocol and pointed at the real electronics catalog: tools (score_deal,
recommend, search_deals), a resource (catalog stats over the 270-item snapshot),
and a prompt template. Run as: `python -m dealfinder.mcp_server`.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .dealmodel import LinearModel
from .dealscore import fair_price, median_signal, residual_fraction, verdict
from .features import feature_matrix, featurize
from .recommend import content_recommend, load_catalog_embeddings
from .search import cosine_rank
from .snapshot import load_snapshot
from .tools import load_catalog

# Build the catalog-backed state once, at import: real snapshot products, their
# cached title embeddings, per-category price models, and same-query medians.
_catalog, _emb = load_catalog_embeddings(load_catalog())
_idx = {p.id: i for i, p in enumerate(_catalog)}
_medians = {r["id"]: r["median_price_at_capture"] for r in load_snapshot()}

_by_cat: dict[str, list] = {}
for _p in _catalog:
    _by_cat.setdefault(_p.category, []).append(_p)
_models = {
    c: LinearModel().fit(feature_matrix(ps), [p.price for p in ps])
    for c, ps in _by_cat.items() if len(ps) >= 3
}


def _fair_price(p) -> float:
    model = _models.get(p.category)
    return fair_price(model, featurize(p)) if model else p.price


mcp = FastMCP("dealfinder")


@mcp.tool()
def score_deal(product_id: str) -> dict:
    """Price, fair price, median signal, and the two-signal deal verdict."""
    p = _catalog[_idx[product_id]]
    fp = _fair_price(p)
    v = verdict(p.price, _medians.get(product_id, p.price), fp)
    return {
        "id": product_id, "title": p.title, "price": p.price,
        "fair_price": round(fp, 2),
        "median_signal": round(median_signal(p.price, _medians.get(product_id, p.price)), 3),
        "residual_frac": round(residual_fraction(p.price, fp), 3),
        "verdict": v.label,
    }


@mcp.tool()
def recommend(product_id: str, k: int = 3) -> list[dict]:
    """k products similar to the given one (content-based on title embeddings)."""
    recs = content_recommend(_idx[product_id], _emb, k, standardize=False)
    return [{"id": _catalog[j].id, "title": _catalog[j].title,
             "price": _catalog[j].price} for j in recs]


@mcp.tool()
def search_deals(query: str, k: int = 5) -> list[dict]:
    """Semantic search the catalog; returns matches with their deal verdict."""
    from .embed import embed_texts

    qv = embed_texts([query])[0]
    out = []
    for i, _ in cosine_rank(qv, _emb, k):
        p = _catalog[i]
        fp = _fair_price(p)
        out.append({"id": p.id, "title": p.title, "price": p.price,
                    "verdict": verdict(p.price, _medians.get(p.id, p.price), fp).label})
    return out


@mcp.resource("dealfinder://catalog/stats")
def catalog_stats() -> str:
    """Quick catalog summary over the frozen snapshot."""
    n = len(_catalog)
    cats = len({p.category for p in _catalog})
    avg = sum(p.price for p in _catalog) / n
    return f"{n} electronics listings across {cats} categories; average price ${avg:.0f}"


@mcp.prompt()
def find_a_deal(category: str = "noise cancelling headphones") -> str:
    """A starter prompt for finding a good deal."""
    return f"Find the best-value {category} in the catalog and explain why it's a good deal."


if __name__ == "__main__":
    mcp.run()
