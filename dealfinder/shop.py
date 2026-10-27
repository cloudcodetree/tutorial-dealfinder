"""The shopper's scorer: one place that turns live offers into rated deals.

Every signal asks the license first (licensing.py). A row from a store that may
not be mixed with others is dropped. A row from a store whose terms forbid
ratings stays, unrated. Only rows that may be rated and embedded feed the peer
estimate. `/ranked` (the lab) and, from Task 6, the shopper `/search` share it.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from . import licensing

NOT_RATED_REASON = "Not rated: this store's terms don't allow price ratings."


def _embed_texts(texts):
    """Title and query embeddings, through the in-process cache (the test patch point)."""
    from .embed import embed_texts_cached

    return embed_texts_cached(texts)


@lru_cache(maxsize=1)
def _models() -> dict:
    """The per-category price models, trained once on the frozen teaching snapshot."""
    from .rag import _category_models
    from .tools import load_catalog

    return _category_models(load_catalog())


def peer_fair_prices(offers: list[dict]) -> dict[int, float]:
    """Category-agnostic fallback fair price: each offer's fair price is the median
    price of its k nearest SEMANTIC neighbors within this result set.

    Embed every offer's title once, then for offer i take the median price of its
    most-similar peers. This gives a second signal for ANY search (not just the
    electronics the trained models cover): an item far cheaper than its close peers
    is suspicious, while one cheap-but-consistent-with-its-peers is a genuine deal.
    It's the graceful-degradation layer under the trained per-category model.
    Returns {index: peer_fair}; offers with too few neighbors are omitted."""
    if len(offers) < 3:
        return {}
    try:
        import numpy as np

        embs = np.asarray(_embed_texts([o["title"] for o in offers]), dtype=float)
        embs /= np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9
        sims = embs @ embs.T
        prices = np.array([float(o["price"]) for o in offers])
        out: dict[int, float] = {}
        for i in range(len(offers)):
            nbrs = [j for j in np.argsort(-sims[i]) if j != i][:5]
            if len(nbrs) >= 2:
                out[i] = float(np.median(prices[nbrs]))
        return out
    except Exception:
        return {}


def deal_reason(verdict, m, rf, fair, basis) -> str:
    """The human-readable 'why' for a verdict — domain copy lives here (backend),
    not in the page, so the UI only displays it."""
    if verdict is None:
        return "Ranked by value only — too few similar offers to estimate a fair price."
    pct = round(m * 100)
    src = "the price model" if basis == "model" else "similar offers"
    ref = f"~${fair:.0f}" if fair else "the estimate"
    if verdict == "deal":
        return f"{pct}% under the median and consistent with {src} ({ref}) — a genuine deal."
    if verdict == "suspicious":
        return (f"Looks {pct}% under the median, but far below {src} ({ref}) — "
                "too good to be true (likely an accessory or a mislisting).")
    if verdict == "overpriced":
        return f"Above the market median and above {src} ({ref})."
    return f"Near the market median and {src} ({ref})."


def offer_slug(title: str, sku: str | None) -> str | None:
    """A stable URL slug for a Best Buy item: ``<title words>-bestbuy-<sku>``.

    The title part is folded to ASCII, lowercased, joined with single hyphens and
    cut to at most 60 characters at a hyphen. No SKU, no slug."""
    if not sku:
        return None
    words = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    words = re.sub(r"[^a-z0-9]+", "-", words).strip("-")
    if len(words) > 60:
        cut = words[:61]
        words = cut[:cut.rfind("-")] if "-" in cut else words[:60]
        words = words.strip("-")
    tail = "bestbuy-" + re.sub(r"[^a-z0-9]+", "-", str(sku).lower()).strip("-")
    return f"{words}-{tail}" if words else tail


def _value(x: dict) -> float:
    s = (x["pct_under_median"] or 0) / 100.0
    if x["verdict"] == "suspicious":
        return s - 1.0        # too-good-to-be-true sinks below genuine deals
    if x["verdict"] == "overpriced":
        return s - 0.5
    return s


def score_offers(offers: list[dict], median: float) -> list[dict]:
    """Rate each offer with the two-signal verdict, under each store's license.

    The fair price comes from the best available estimate: the trained
    per-category model, else a peer estimate from similar offers in this result
    set, else none (value only). `median` is the market median over the rows
    that may be rated. Rows come back sorted by value, not truncated."""
    from .dealscore import fair_price, median_signal, render_badge, residual_fraction
    from .extract import guess_category
    from .features import featurize
    from .schema import Product

    rows = [r for r in offers if licensing.may_comingle(r.get("source", ""))]
    rated = [i for i, r in enumerate(rows) if licensing.may_verdict(r["source"])]
    peer_idx = [i for i in rated if licensing.may_embed(rows[i]["source"])]
    peers = peer_fair_prices([rows[i] for i in peer_idx])
    peer_fair = {peer_idx[j]: v for j, v in peers.items()}
    models = _models()

    scored = []
    for i, r in enumerate(rows):
        price = float(r["price"])
        cat = guess_category(r["title"])
        verdict = fair = rf = basis = pct = None
        if i in rated:
            m = median_signal(price, median) if median else 0.0
            model = models.get(cat) if cat else None
            if model is not None:
                p = Product(id=r["id"], title=r["title"], brand=r.get("brand"),
                            category=cat, price=price, url=r.get("url") or "",
                            source=r.get("source") or "live")
                fair, basis = float(fair_price(model, featurize(p))), "model"
            elif i in peer_fair and peer_fair[i] > 0:
                fair, basis = peer_fair[i], "peers"
            if fair is not None:
                rf = residual_fraction(price, fair)
                verdict = render_badge(m, rf).lower()   # deal / suspicious / fair / overpriced
            pct = round(m * 100, 1)
            reason = deal_reason(verdict, m, rf, fair, basis)
        else:
            reason = NOT_RATED_REASON
        scored.append({
            "id": r["id"], "sku": r.get("sku"), "slug": offer_slug(r["title"], r.get("sku")),
            "title": r["title"], "brand": r.get("brand"),
            "price": round(price, 2), "regular_price": r.get("regular_price"),   # display only
            "source": r.get("source"),
            "verdict": verdict,
            "pct_under_median": pct,
            "fair": round(fair, 2) if fair is not None else None,
            "residual_frac": round(rf, 3) if rf is not None else None,
            "basis": basis,               # "model" | "peers" | None (value-only or not rated)
            "category": cat,
            "reason": reason,
            "url": r.get("url"), "image_url": r.get("image_url"),
            "fetched_at": r.get("fetched_at"),
        })
    scored.sort(key=_value, reverse=True)
    return scored
