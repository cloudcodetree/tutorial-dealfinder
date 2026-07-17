"""Agentic RAG — retrieval as a repeated, *judged* tool call, not a one-shot step.

Single-shot RAG (Part 14) retrieves once and answers. That is fine when the first
retrieval is good. But a vague query — "cheap wireless earbuds" — pulls in refurb
traps and off-target items, and answering from that weak evidence produces a weak
recommendation. Agentic RAG closes the loop:

    retrieve → JUDGE sufficiency → if weak, REFORMULATE and retrieve again → answer

The agent decides *whether the evidence is good enough* and *what to search next*.
Nothing here is a new model: it reuses the Part 5 hybrid+value retriever
(`rag.retrieve`), the two-signal verdicts already attached to each item, and the
grounded generation + faithfulness guard from Part 14 (`rag.answer` /
`rag.is_grounded`). The only new machinery is the sufficiency gate and a
corpus-grounded query reformulator.

Determinism: the sufficiency gate is a pure function of the retrieved verdicts,
and the reformulator expands the query with a capability phrase *mined from the
frozen snapshot* (not hand-authored), so the whole loop is reproducible offline.
In production the reformulator is an LLM; it is injectable exactly like the
generator in `rag.py`.
"""
from __future__ import annotations

import re
import collections
from dataclasses import dataclass, field

from . import rag
from .recommend import load_catalog_embeddings

# Vague price adjectives that pull in traps without adding a real constraint.
_VAGUE = {"cheap", "good", "best", "top", "nice", "affordable", "budget"}

# A phrase is a useful *capability* expansion only if it names a feature, not a
# brand or a generic noun. These keys are what makes "noise cancelling" a good
# expansion and "sony wh" a bad one.
_CAPABILITY_KEYS = {
    "noise", "cancelling", "canceling", "wireless", "waterproof", "mechanical",
    "gaming", "portable", "hybrid", "active", "over", "true",
}

# Strong discriminators sharpen a vague query far more than generic ones
# ("noise cancelling" filters traps; "true wireless" barely narrows). We try
# strong phrases first so the loop converges in the fewest hops.
_STRONG = {"noise", "cancelling", "canceling", "waterproof", "mechanical", "gaming", "hybrid", "active"}


@dataclass
class Hop:
    """One retrieval hop: the query tried, the gate's decision, and why."""

    query: str
    sufficient: bool
    reason: str
    verdicts: list[str]  # the k retrieved verdicts, in rank order


@dataclass
class AgenticAnswer:
    """The final grounded answer plus the full retrieval trajectory."""

    answer: str
    grounded: bool
    hops: list[Hop] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    used_llm: bool = False


def sufficiency(items: list[rag.RetrievedItem]) -> tuple[bool, str]:
    """Is the retrieved set strong enough to answer from — a pure gate on verdicts.

    Sufficient when the top pick is a genuine DEAL, there are at least two DEALs to
    choose between, and honest deals are not outnumbered by SUSPICIOUS traps. A set
    dominated by traps/overpriced items means the query was too vague to trust.
    """
    if not items:
        return False, "no items retrieved"
    deals = sum(1 for it in items if it.verdict == "deal")
    suspicious = sum(1 for it in items if it.verdict == "suspicious")
    top = items[0].verdict
    if top != "deal":
        return False, f"top result is {top.upper()}, not a DEAL"
    if deals < 2:
        return False, f"only {deals} DEAL in top-{len(items)} — too thin to recommend"
    if suspicious >= deals:
        return False, f"{suspicious} SUSPICIOUS traps vs {deals} DEALs — query too vague"
    return True, f"{deals} DEALs, top is a DEAL, {suspicious} traps — good evidence"


def _capability_lexicon(products) -> dict[str, list[str]]:
    """Per-category capability phrases mined from the frozen snapshot titles.

    Ranked bigrams that contain a capability keyword — corpus-derived, not
    hand-written. These are the terms a weak query is missing.
    """
    per_cat: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for p in products:
        cat = getattr(p, "category", "") or "other"
        toks = re.findall(r"[a-z]+", p.title.lower())
        for a, b in zip(toks, toks[1:]):
            phrase = f"{a} {b}"
            if _CAPABILITY_KEYS & {a, b}:
                per_cat[cat][phrase] += 1
    # Rank strong discriminators first, then by corpus frequency.
    def rank(item):
        phrase, freq = item
        strong = 1 if _STRONG & set(phrase.split()) else 0
        return (strong, freq)
    return {
        cat: [ph for ph, _ in sorted(c.items(), key=rank, reverse=True)[:8]]
        for cat, c in per_cat.items()
    }


def _strip_vague(query: str) -> str:
    kept = [w for w in query.split() if w.lower() not in _VAGUE]
    return " ".join(kept) if kept else query


def reformulate(base: str, items: list[rag.RetrievedItem], lexicon: dict, tried: set[str]) -> tuple[str, str | None]:
    """Expand the ORIGINAL (de-vagued) query with the best untried capability term.

    Expands from ``base`` — the original query with vague price words stripped —
    not the previous hop's text, so reformulations stay clean instead of piling up.
    Picks the highest-ranked capability phrase for the retrieved category that the
    base lacks and hasn't been tried, plus an explicit value intent. Returns the
    new query and the phrase used (``None`` if the lexicon is exhausted). In
    production an LLM does this; the corpus-mined rule keeps the offline path
    reproducible.
    """
    base_words = set(base.split())
    cat = items[0].category if items else "other"
    for phrase in lexicon.get(cat, []):
        if phrase in tried or set(phrase.split()).issubset(base_words):
            continue
        # Append only the words the base lacks, so queries stay clean (no
        # "monitor ... monitor") while preserving the phrase's order.
        novel = " ".join(w for w in phrase.split() if w not in base_words)
        return f"{base} {novel} deal".strip(), phrase
    return f"{base} deal".strip(), None


def agentic_answer(query: str, max_hops: int = 3, products=None, embeddings=None) -> AgenticAnswer:
    """Retrieve → judge → reformulate & retry if weak → answer, grounded.

    Returns the final grounded answer plus every hop's query and gate decision, so
    the trajectory is inspectable. Stops as soon as the evidence is sufficient (or
    after ``max_hops``), then generates the answer from the last hop's query with
    the Part 14 grounded generator + faithfulness guard.
    """
    if products is None:
        products, embeddings = load_catalog_embeddings()
    lexicon = _capability_lexicon(products)

    hops: list[Hop] = []
    base = _strip_vague(query).lower()
    current = query
    tried: set[str] = set()
    items: list[rag.RetrievedItem] = []
    for _ in range(max_hops):
        items = rag.retrieve(current, k=5, products=products, embeddings=embeddings)
        ok, reason = sufficiency(items)
        hops.append(Hop(current, ok, reason, [it.verdict for it in items]))
        if ok:
            break
        current, phrase = reformulate(base, items, lexicon, tried)
        if phrase is not None:
            tried.add(phrase)

    # Generate the grounded answer from the final (best) hop's query.
    final = rag.answer(current, k=5)
    return AgenticAnswer(
        answer=final.answer,
        grounded=final.grounded,
        hops=hops,
        sources=final.sources,
        used_llm=final.used_llm,
    )
