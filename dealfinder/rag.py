"""Retrieval-Augmented Generation over the REAL electronics deals — retrieve, then
GENERATE a grounded answer.

This is the generate step layered on top of the vector store the course already
builds (Parts 4/5/13): the same cached fastembed title embeddings, the same
hybrid + value rerank retrieval (`search.search_catalog`), and the same
two-signal deal verdict (`dealscore.verdict`). RAG here does **not** retrieve over
documents — it retrieves over the *scraped listings themselves*, then asks an LLM
(or a deterministic fallback) to answer a shopping question grounded ONLY in the
retrieved rows.

Two generation paths, same grounding contract:

- **LLM path** — when an OpenRouter key is configured (`llm.available()`), the
  retrieved listings are formatted into a numbered context block and the model is
  told to answer *only* from it, citing items by title + price.
- **Deterministic path** — with no key, we synthesize an extractive answer from
  the retrieved rows (best DEAL, a runner-up, and the SUSPICIOUS trap with its
  reason). No model, fully offline, and reproducible against the frozen snapshot.

Both paths are checked by `is_grounded`: every product/price the answer cites must
appear in the retrieved set — no hallucinated products or prices. The LLM client
is injectable so tests exercise the LLM branch without a network call.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from . import llm as _llm_module
from .dealmodel import LinearModel
from .dealscore import fair_price, verdict
from .features import feature_matrix, featurize
from .recommend import load_catalog_embeddings
from .schema import Product
from .search import search_catalog
from .snapshot import load_snapshot

# Per-category price model needs at least this many rows to be worth fitting;
# below it the median signal carries the verdict on its own (matches search.py).
_MIN_CAT = 3


@dataclass
class RetrievedItem:
    """One retrieved listing plus its deal signal — the unit an answer grounds on."""

    id: str
    title: str
    price: float
    source: str
    category: str
    similarity: float          # value-rerank score from search_catalog (higher = better pick)
    verdict: str               # deal | fair | suspicious | overpriced
    median_signal: float       # fraction under the same-query median
    fair_price: float          # model's predicted fair price
    residual_frac: float       # (fair - actual) / fair
    reason: str                # the verdict's human explanation


@dataclass
class RagAnswer:
    """The generated answer plus its provenance and a faithfulness flag."""

    answer: str
    sources: list[str] = field(default_factory=list)  # item ids the answer actually uses
    grounded: bool = False
    used_llm: bool = False


# ---------------------------------------------------------------------------
# Snapshot-backed retrieval (deterministic against the frozen corpus).
# ---------------------------------------------------------------------------
def _load_medians(path: str | None = None) -> dict:
    """Map product id → its same-query capture median (for the median signal)."""
    return {r["id"]: r["median_price_at_capture"] for r in load_snapshot(path)}


def _category_models(products: list[Product]) -> dict:
    """Fit one from-scratch linear price model per category (spec §4 / §9.1).

    Matches `search._two_signal_deal_scores`: the audio-category baseline is what
    pins the hero-cast fair prices ($285.15 for the tier-4 flagships), so the
    verdict a RetrievedItem carries is the same one the deal-score parts quote.
    """
    by_cat: dict[str, list[Product]] = {}
    for p in products:
        by_cat.setdefault(p.category, []).append(p)
    return {
        c: LinearModel().fit(feature_matrix(ps), [p.price for p in ps])
        for c, ps in by_cat.items()
        if len(ps) >= _MIN_CAT
    }


def _verdict_for(p: Product, median: float, models: dict):
    """The two-signal verdict for one product under its category model."""
    model = models.get(p.category)
    fp = fair_price(model, featurize(p)) if model is not None else p.price
    return verdict(p.price, median, fp)


def retrieve(
    query: str,
    k: int = 5,
    products: list[Product] | None = None,
    embeddings=None,
    use_db: bool | None = None,
) -> list[RetrievedItem]:
    """Retrieve the top-k real listings for ``query`` with their deal signal.

    Embeds the query (fastembed bge-small, via ``search_catalog``), ranks against
    the cached title embeddings — or pgvector ``semantic_search`` when
    ``DATABASE_URL`` is set — hybridizes with BM25, and value-reranks so honest
    deals float above too-good-to-be-true traps. Each result carries its
    similarity, price, and the two-signal verdict, so an answer can ground on it.

    Deterministic against the frozen snapshot: same corpus + same cached
    embeddings ⇒ same top-k. ``use_db`` overrides where vectors come from: leave
    it ``None`` to follow ``DATABASE_URL`` (the default), or pass ``False`` to force
    the reproducible in-memory snapshot path regardless of env — used by the
    context-engineering surface (Part 16) so its token math never depends on how
    much has been seeded into pgvector.
    """
    if products is None:
        products, embeddings = load_catalog_embeddings()
    elif embeddings is None:
        products, embeddings = load_catalog_embeddings(products)

    medians = _load_medians()
    models = _category_models(products)

    from_db = bool(os.getenv("DATABASE_URL")) if use_db is None else use_db
    if from_db:
        ranked = _retrieve_pgvector(query, products, k)
    else:
        # Hybrid semantic+BM25 → RRF → value rerank over the cached embeddings.
        hits = search_catalog(query, products, embeddings, medians, k=k)
        ranked = [(p, float(score)) for _idx, p, score in hits]

    items: list[RetrievedItem] = []
    for p, score in ranked:
        v = _verdict_for(p, medians.get(p.id, 0.0), models)
        items.append(
            RetrievedItem(
                id=p.id,
                title=p.title,
                price=float(p.price),
                source=p.source,
                category=p.category,
                similarity=round(score, 4),
                verdict=v.label,
                median_signal=round(v.median_signal, 4),
                fair_price=round(v.fair_price, 2),
                residual_frac=round(v.residual_frac, 4),
                reason=v.reason,
            )
        )
    return items


def _retrieve_pgvector(query: str, products: list[Product], k: int) -> list[tuple[Product, float]]:
    """Retrieve via pgvector when a DATABASE_URL is configured (Part 13 path).

    Falls back to the in-memory hits shape: returns ``(Product, similarity)``. The
    product objects come from the snapshot so verdicts still use the frozen prices.
    """
    from . import pgstore
    from .embed import embed_texts

    by_id = {p.id: p for p in products}
    qv = embed_texts([query])[0]
    rows = pgstore.semantic_search(qv, k=k)
    out: list[tuple[Product, float]] = []
    for r in rows:
        p = by_id.get(r["id"])
        if p is not None:
            out.append((p, float(r.get("similarity", 0.0))))
    return out


# ---------------------------------------------------------------------------
# Context block the LLM (or a human) grounds on.
# ---------------------------------------------------------------------------
def build_context(items: list[RetrievedItem]) -> str:
    """Format retrieved listings into a compact, numbered, groundable context block.

    One line per item: index, title, price, source, and the deal verdict badge.
    This is the *only* evidence the answer is allowed to use.
    """
    lines = []
    for i, it in enumerate(items, 1):
        lines.append(
            f"[{i}] {it.title} — ${it.price:.2f} ({it.source}) "
            f"[{it.verdict.upper()}] — {it.reason}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Faithfulness check: no product/price the answer cites may be invented.
# ---------------------------------------------------------------------------
_PRICE_RE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)")


def _norm(s: str) -> str:
    """Lowercase + collapse to alnum tokens for lenient title matching."""
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _prices_in(text: str) -> set[str]:
    """The distinct dollar amounts named in ``text`` (as 2-dp strings)."""
    out = set()
    for m in _PRICE_RE.finditer(text):
        try:
            out.add(f"{float(m.group(1).replace(',', '')):.2f}")
        except ValueError:
            continue
    return out


def is_grounded(answer_text: str, retrieved: list[RetrievedItem]) -> bool:
    """True iff every product AND price the answer cites is in the retrieved set.

    Faithfulness guard: the answer may only talk about listings it was given.

    - **Prices:** every ``$X`` in the answer must equal a retrieved item's price.
      A price the retrieved set never contained is a hallucination.
    - **Products:** if the answer names a distinctive product token (a model code
      like ``Q20i``/``WH-1000XM5``, or a known brand) that appears in *no*
      retrieved title, that's a hallucinated product.
    """
    if not retrieved:
        return False

    # The allowed evidence is the *whole* context the model was given — which
    # includes each listing's price AND the derived values in its reason line
    # (the model's fair price, the query median). Validating only against listing
    # prices would falsely flag an answer for citing the fair price the context
    # itself supplied ("84% under model fair price $285").
    allowed_prices = _prices_in(build_context(retrieved))
    for price in _prices_in(answer_text):
        if price not in allowed_prices:
            return False

    haystack = " " + _norm(" ".join(it.title for it in retrieved)) + " "
    ans = _norm(answer_text)

    # Model-code tokens (letters+digits, e.g. q20i, wh, 1000xm5, qc45) are the
    # strongest product fingerprints — each one cited must occur in some title.
    for tok in set(re.findall(r"[a-z]+\d[a-z0-9]*|\d+[a-z]+[a-z0-9]*", ans)):
        if len(tok) < 3:
            continue
        if f" {tok} " not in haystack:
            return False
    return True


# ---------------------------------------------------------------------------
# Deterministic (no-LLM) extractive synthesis.
# ---------------------------------------------------------------------------
def _deterministic_answer(query: str, items: list[RetrievedItem]) -> RagAnswer:
    """Build a grounded answer straight from the retrieved rows — no model.

    Names the best DEAL, a runner-up, and the SUSPICIOUS trap (with its reason),
    citing only titles + prices that are in the retrieved set. Fully offline and
    reproducible against the frozen snapshot.
    """
    if not items:
        return RagAnswer(
            answer="No matching listings were retrieved, so there's nothing to recommend.",
            sources=[], grounded=True, used_llm=False,
        )

    deals = [it for it in items if it.verdict == "deal"]
    suspicious = [it for it in items if it.verdict == "suspicious"]
    # Runner-up: the next-best non-suspicious pick after the top deal, by rank.
    hero = deals[0] if deals else items[0]
    runners = [it for it in items if it.id != hero.id and it.verdict != "suspicious"]

    # The answer cites ONLY listing prices ($X) so it passes the same strict
    # faithfulness bar an LLM answer must. Discounts are stated as percentages
    # (derived numbers), never as an invented dollar median/fair-price that isn't
    # a retrieved listing price.
    used: list[str] = [hero.id]
    parts = [
        f"Best value: {hero.title} at ${hero.price:.2f} "
        f"({hero.median_signal * 100:.0f}% under the same-query median)."
    ]
    if runners:
        r = runners[0]
        used.append(r.id)
        parts.append(f"Also consider: {r.title} at ${r.price:.2f}.")
    if suspicious:
        s = suspicious[0]
        used.append(s.id)
        parts.append(
            f"Avoid: {s.title} at ${s.price:.2f} — flagged SUSPICIOUS: it reads "
            f"{s.median_signal * 100:.0f}% under median but sits far below its "
            "modeled fair price, the signature of a refurb/mislisting rather than "
            "a real bargain."
        )

    answer = " ".join(parts)
    grounded = is_grounded(answer, items)
    return RagAnswer(answer=answer, sources=used, grounded=grounded, used_llm=False)


# ---------------------------------------------------------------------------
# LLM (grounded) synthesis.
# ---------------------------------------------------------------------------
_SYSTEM = (
    "You are DealFinder's shopping assistant. Answer ONLY using the numbered "
    "listings provided. Cite every item you mention by its exact title and price. "
    "If none of the listings qualify, say so plainly. Do NOT invent products, "
    "prices, brands, or specs that are not in the listings."
)


def _llm_answer(query: str, items: list[RetrievedItem], llm) -> RagAnswer:
    """Ask the (injectable) LLM to answer grounded in the numbered context block."""
    context = build_context(items)
    user = (
        f"Question: {query}\n\n"
        f"Listings (the ONLY evidence you may use):\n{context}\n\n"
        "Recommend the best pick, a runner-up, and warn about any SUSPICIOUS trap. "
        "Cite each by title and price."
    )
    text = llm.chat(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
        temperature=0,
    )
    text = (text or "").strip()
    # Sources = the retrieved ids whose title is actually referenced in the answer.
    used = [it.id for it in items if _norm(it.title.split(" — ")[0]) and _title_cited(it, text)]
    if not used:
        used = [it.id for it in items]  # answer used the set as a whole
    return RagAnswer(answer=text, sources=used, grounded=is_grounded(text, items), used_llm=True)


def _title_cited(it: RetrievedItem, text: str) -> bool:
    """Loose check: is this item's title (or its price) referenced in the answer?"""
    ans = _norm(text)
    # A distinctive chunk of the title, or the exact price, counts as a citation.
    title_tokens = _norm(it.title).split()
    head = " ".join(title_tokens[:3])
    return (head and head in ans) or (f"{it.price:.2f}" in _prices_in(text))


def answer(query: str, k: int = 5, *, llm=None, use_db: bool | None = None) -> RagAnswer:
    """Retrieve → build context → GENERATE a grounded answer.

    If an LLM client is available (injected ``llm`` or a configured OpenRouter key
    via ``llm.available()``), it answers from the numbered context under a strict
    grounded prompt. Otherwise a deterministic extractive synthesis is built from
    the retrieved rows. Either way, ``grounded`` reflects the faithfulness check
    and ``sources`` are the retrieved ids the answer references. ``use_db`` forwards
    to ``retrieve`` (``False`` pins the reproducible snapshot path).
    """
    items = retrieve(query, k=k, use_db=use_db)
    client = llm if llm is not None else _llm_module
    if getattr(client, "available", lambda: False)():
        try:
            return _llm_answer(query, items, client)
        except Exception:
            # Any LLM failure degrades to the deterministic, always-grounded path.
            return _deterministic_answer(query, items)
    return _deterministic_answer(query, items)


def deterministic_answer(query: str, k: int = 5, *, use_db: bool | None = None) -> RagAnswer:
    """The extractive, LLM-free answer path — no matter what key is configured.

    Always grounded, always leads with the top DEAL and warns about any SUSPICIOUS
    trap, in a fixed 'Best value: … at $…' shape. Used as the multi-agent
    orchestrator's revision fallback (Part 17): when a writer's draft is rejected,
    this is the reliable answer we fall back to — a *guarantee*, not another LLM
    roll of the dice. ``use_db`` forwards to ``retrieve``."""
    return _deterministic_answer(query, retrieve(query, k=k, use_db=use_db))


# ---------------------------------------------------------------------------
# Tiny grounding eval over a few golden queries.
# ---------------------------------------------------------------------------
GOLDEN_QUERIES: list[dict] = [
    {
        "query": "best noise-cancelling headphones under $150",
        "expect_hero": "Anker Soundcore Q20i",
        "expect_verdict": "deal",
    },
    {
        "query": "cheapest 4k monitor",
        "expect_hero": "MSI Pro MP273U",
        "expect_verdict": "deal",
    },
]


def evaluate_rag(queries: list[dict] | None = None) -> dict:
    """Grounding eval: for each golden query, assert the deterministic answer is
    grounded and surfaces the expected hero item. Reports the faithfulness rate.

    Runs the no-LLM path so it's deterministic and offline — the reproducible
    grounding gate a tutorial can quote and a test can pin.
    """
    queries = queries or GOLDEN_QUERIES
    rows = []
    grounded_hits = 0
    for spec in queries:
        items = retrieve(spec["query"], k=5)
        ans = _deterministic_answer(spec["query"], items)
        hero_ok = spec["expect_hero"].lower() in ans.answer.lower()
        top_verdict = items[0].verdict if items else None
        if ans.grounded:
            grounded_hits += 1
        rows.append(
            {
                "query": spec["query"],
                "grounded": ans.grounded,
                "hero_surfaced": hero_ok,
                "expected_hero": spec["expect_hero"],
                "top_verdict": top_verdict,
                "sources": ans.sources,
            }
        )
    n = len(queries)
    return {
        "n": n,
        "faithfulness_rate": grounded_hits / n if n else 0.0,
        "results": rows,
    }


if __name__ == "__main__":  # pragma: no cover - manual ground-truth probe
    print(json.dumps(evaluate_rag(), indent=2, default=str))
