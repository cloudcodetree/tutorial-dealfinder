"""The shopper's scorer: one place that turns live offers into rated deals.

Every signal asks the license first (licensing.py). A row from a store that may
not be mixed with others is dropped. A row from a store whose terms forbid
ratings stays, unrated. Only rows that may be rated and embedded feed the peer
estimate. `/ranked` (the lab) and, from Task 6, the shopper `/search` share it.
"""
from __future__ import annotations

import logging
import os
import re
import statistics
import threading
import time
import unicodedata
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache

from . import licensing
from .aggregate import _utc_iso, aggregate
from .live_sources import EBAY

NOT_RATED_REASON = "Not rated: this store's terms don't allow price ratings."
CHECK_MODE_REASON = "Ratings are off for store listings. Use Check a deal to rate a price you found."
_MODES = ("live", "check")
_warned_modes: set[str] = set()
EBAY_NOTE = "Listings from eBay. Not compared or rated."
# eBay's terms cap listing age at 6 hours (licensing.py); this box keeps its own
# rows 15 minutes, and nothing else ever holds them.
EBAY_CACHE_TTL_S = 900
_EBAY_CACHE_MAX = 256
_ebay_cache: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
_ebay_lock = threading.Lock()


def _now() -> float:
    return time.monotonic()


def verdict_mode() -> str:
    """``live`` (verdicts on store listings) or ``check`` (only Check a deal rates).

    Env DEALFINDER_VERDICT_MODE; unset means ``live``. Any other value fails
    closed to ``check``, which shows no verdicts, and logs one warning."""
    raw = os.getenv("DEALFINDER_VERDICT_MODE")
    if raw is None:
        return "live"
    if raw in _MODES:
        return raw
    if raw not in _warned_modes:
        _warned_modes.add(raw)
        logging.getLogger("dealfinder").warning(
            "DEALFINDER_VERDICT_MODE=%r is not live or check; showing no verdicts", raw)
    return "check"


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
    if verdict_mode() == "check":
        return [_unrated(r, CHECK_MODE_REASON, guess_category(r["title"])) for r in rows]
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
            **_unrated(r, reason, cat),
            "verdict": verdict,
            "pct_under_median": pct,
            "fair": round(fair, 2) if fair is not None else None,
            "residual_frac": round(rf, 3) if rf is not None else None,
            "basis": basis,               # "model" | "peers" | None (value-only or not rated)
        })
    scored.sort(key=_value, reverse=True)
    return scored


def _unrated(r: dict, reason: str, category: str | None) -> dict:
    """One result row in the contract shape with every price signal empty."""
    return {
        "id": r["id"], "sku": r.get("sku"), "slug": offer_slug(r["title"], r.get("sku")),
        "title": r["title"], "brand": r.get("brand"),
        "price": round(float(r["price"]), 2), "regular_price": r.get("regular_price"),   # display only
        "source": r.get("source"),
        "verdict": None, "pct_under_median": None, "fair": None, "residual_frac": None, "basis": None,
        "category": category,
        "reason": reason,
        "url": r.get("url"), "image_url": r.get("image_url"),
        "fetched_at": r.get("fetched_at"),
    }


def _ebay_enabled() -> bool:
    """Sandbox listings are fake, so they never show unless a developer opts in."""
    if not EBAY.available():
        return False
    return not EBAY.is_sandbox() or os.getenv("DEALFINDER_EBAY_ALLOW_SANDBOX") == "1"


def ebay_box(q: str, limit: int = 6) -> dict:
    """The separate "Also on eBay" box: eBay's own listings, in eBay's own order.

    Never rated, scored, ranked against other stores, embedded or stored. The
    rows live only in this module's short cache."""
    if not _ebay_enabled():
        return {"enabled": False, "note": EBAY_NOTE, "items": []}
    key = q.strip().lower()
    now = _now()
    with _ebay_lock:
        hit = _ebay_cache.get(key)
        if hit and now - hit[0] < EBAY_CACHE_TTL_S:
            _ebay_cache.move_to_end(key)
            return {"enabled": True, "note": EBAY_NOTE, "items": hit[1][:limit]}
    try:
        items = [{
            "id": p.id, "title": p.title, "price": p.price, "currency": p.currency, "url": p.url,
            "condition": p.source.split(":", 1)[1] if ":" in p.source else "", "image_url": p.image_url,
        } for p in EBAY.search(q.strip(), limit=limit)[:limit]]
    except Exception:
        return {"enabled": True, "note": EBAY_NOTE, "items": []}
    with _ebay_lock:
        _ebay_cache[key] = (now, items)
        _ebay_cache.move_to_end(key)
        while len(_ebay_cache) > _EBAY_CACHE_MAX:
            _ebay_cache.popitem(last=False)
    return {"enabled": True, "note": EBAY_NOTE, "items": items}


def shop_search(q: str, k: int = 12) -> dict:
    """The shopper search: rated store results, the separate eBay box, attribution.

    The live sources and the eBay box are fetched at the same time."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        live = pool.submit(aggregate, q)
        box = pool.submit(ebay_box, q)
        result = live.result()
        try:
            ebay = box.result()
        except Exception:
            ebay = {"enabled": False, "note": EBAY_NOTE, "items": []}
    mode = verdict_mode()
    offers = result.get("results", [])
    rated = [float(r["price"]) for r in offers if licensing.may_verdict(r.get("source", ""))]
    median = statistics.median(rated) if rated else 0.0
    results = score_offers(offers, median)[:k]
    attribution = []
    for r in results:
        policy = licensing.policy_for(r["source"])
        if policy and policy.attribution and policy.attribution not in attribution:
            attribution.append(policy.attribution)
    return {
        "query": q,
        "mode": mode,
        "count": len(results),
        "median_price": None if mode == "check" else round(median, 2),
        "fetched_at": _utc_iso(datetime.now(timezone.utc)),
        "results": results,
        "ebay": ebay,
        "attribution": attribution,
    }


def _fair_for(title: str) -> tuple[str | None, float | None]:
    """The title's category and the snapshot model's fair price for it.

    The models are trained on the frozen teaching snapshot only, so this never
    reads a live row and never calls the network."""
    from .dealscore import fair_price
    from .extract import guess_category
    from .features import featurize
    from .schema import Product

    cat = guess_category(title)
    model = _models().get(cat) if cat else None
    if model is None:
        return cat, None
    p = Product(id="check", title=title, brand=None, category=cat, price=0.0, url="", source="check")
    return cat, float(fair_price(model, featurize(p)))


def check_deal(title: str, price: float) -> dict:
    """Rate one price the shopper found against our fair price for that model.

    There is no market median for a single price, so the verdict uses the model
    residual alone, with the same thresholds as the two-signal verdict."""
    from .dealscore import DEAL_MEDIAN_FRAC, SUSPICIOUS_RESIDUAL_FRAC, residual_fraction

    cat, fair = _fair_for(title)
    out = {"title": title, "price": price, "category": cat, "fair": None, "residual_frac": None,
           "verdict": None, "basis": None,
           "reason": "We can't estimate a fair price for this kind of product yet."}
    if fair is None:
        return out
    rf = residual_fraction(price, fair)
    n = round(abs(rf) * 100)
    if rf >= SUSPICIOUS_RESIDUAL_FRAC:
        verdict = "suspicious"
        reason = (f"{n}% below our fair price for this model (~${fair:.0f}). That is too far below to be real. "
                  "It may be used, an accessory, or a mislisting.")
    elif rf >= DEAL_MEDIAN_FRAC:
        verdict, reason = "deal", f"{n}% below our fair price for this model (~${fair:.0f})."
    elif rf <= -DEAL_MEDIAN_FRAC:
        verdict, reason = "overpriced", f"{n}% above our fair price for this model (~${fair:.0f})."
    else:
        verdict, reason = "fair", f"Within 15% of our fair price for this model (~${fair:.0f})."
    return {**out, "fair": round(fair, 2), "residual_frac": round(rf, 3), "verdict": verdict,
            "basis": "model", "reason": reason}
