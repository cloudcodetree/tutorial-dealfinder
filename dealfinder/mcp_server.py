"""Expose DealFinder as an MCP server — its tools become callable from any MCP
client (Claude Code, Claude Desktop, …).

Same capabilities you built in earlier parts, now behind the Model Context
Protocol: tools (score_deal, recommend, search_deals), a resource (catalog
stats), and a prompt template. Run as: `python -m dealfinder.mcp_server`.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .deal import deal_score
from .dealmodel import LinearModel
from .features import feature_matrix
from .recommend import content_recommend
from .tools import load_catalog

# Build the catalog-backed state once, at import.
_catalog = load_catalog()
_idx = {p.id: i for i, p in enumerate(_catalog)}
_X = feature_matrix(_catalog)
_model = LinearModel().fit(_X, [p.price for p in _catalog])
_fair = {p.id: float(fp) for p, fp in zip(_catalog, _model.predict(_X))}

mcp = FastMCP("dealfinder")


@mcp.tool()
def score_deal(product_id: str) -> dict:
    """Price, predicted fair price, and deal score (positive = under fair)."""
    p = _catalog[_idx[product_id]]
    return {
        "id": product_id, "price": p.price, "fair": round(_fair[product_id], 2),
        "deal_score": round(deal_score(p.price, _fair[product_id]), 3),
    }


@mcp.tool()
def recommend(product_id: str, k: int = 3) -> list[dict]:
    """k products similar to the given one (content-based)."""
    recs = content_recommend(_idx[product_id], _X, k)
    return [{"id": _catalog[j].id, "title": _catalog[j].title} for j in recs]


@mcp.tool()
def search_deals(query: str, k: int = 5) -> list[dict]:
    """Semantic search the catalog; returns matches with their deal score."""
    from .embed import embed_texts, product_text
    from .search import cosine_rank

    doc_vecs = embed_texts([product_text(p) for p in _catalog])
    qv = embed_texts([query])[0]
    out = []
    for i, _ in cosine_rank(qv, doc_vecs, k):
        p = _catalog[i]
        out.append({"id": p.id, "title": p.title, "price": p.price,
                    "deal_score": round(deal_score(p.price, _fair[p.id]), 3)})
    return out


@mcp.resource("dealfinder://catalog/stats")
def catalog_stats() -> str:
    """Quick catalog summary."""
    avg = sum(p.price for p in _catalog) / len(_catalog)
    return f"{len(_catalog)} products; average price ${avg:.0f}"


@mcp.prompt()
def find_a_deal(category: str = "tent") -> str:
    """A starter prompt for finding a good deal."""
    return f"Find the best-value {category} in the catalog and explain why it's a good deal."


if __name__ == "__main__":
    mcp.run()
