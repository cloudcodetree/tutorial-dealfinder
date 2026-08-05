"""Multi-agent orchestration — the writer/reviewer pattern over deals.

One agent can't reliably check its own work: the context that produced an answer
is biased toward believing it. So we split the job across two agents with
*isolated* contexts:

- **Recommender (writer)** — retrieves and generates a grounded recommendation
  (the Part 14 pipeline).
- **Reviewer (critic)** — re-retrieves the evidence *independently* and
  adversarially checks the answer: is every claim grounded, and is the lead pick a
  genuine DEAL rather than the SUSPICIOUS trap? The reviewer sees only the answer
  text plus its own retrieval — never the writer's reasoning.

The orchestrator runs writer → reviewer, and if the review fails it revises (here:
fall back to the always-grounded deterministic answer). This is the same shape as
a researcher/verifier or proposer/judge panel — isolation is what makes the second
opinion worth anything.

Deterministic and offline: both agents retrieve over the frozen snapshot, and the
checks are pure functions of the two-signal verdicts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import rag


@dataclass
class Review:
    """The reviewer's verdict on a recommendation."""

    approved: bool
    issues: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)


@dataclass
class Orchestrated:
    """The final answer plus the writer→reviewer trail."""

    answer: str
    approved: bool
    review: Review
    revised: bool
    used_llm: bool


# Both agents retrieve over the frozen snapshot (this module's contract), so the
# writer/reviewer trail is reproducible regardless of any attached DATABASE_URL.
_SNAPSHOT = False


def recommend(query: str, k: int = 5, *, llm=None) -> rag.RagAnswer:
    """Writer: retrieve + generate a grounded recommendation (Part 14 pipeline)."""
    return rag.answer(query, k=k, llm=llm, use_db=_SNAPSHOT)


def _lead_title(answer_text: str) -> str:
    """The product named as the lead pick — the title right after the 'Best value'/
    'Best pick' cue, up to the price. '' if the answer has no identifiable lead.

    Robust to both answer shapes the writers produce: the deterministic template
    ('Best value: <title> at $44.99') AND a real LLM's markdown ('**Best pick**\\n-
    *<title> — $44.99*'). Without this the reviewer can't locate the lead in any
    LLM-written draft and would reject every one of them."""
    # Strip markdown emphasis so '**Best pick**' and '*Title*' match cleanly.
    text = re.sub(r"[*_`#]+", "", answer_text)
    # 'Best value'/'Best pick', then any colon / newline / list-bullet, then the
    # title, up to the first price delimiter ('at $', a dash before '$', '($', '$').
    m = re.search(
        r"Best\s+(?:value|pick)\s*[:.\-]?\s*\n?\s*[-*•]?\s*"
        r"(.+?)\s*(?:\bat\s+\$|[-–—]\s*\$|\(\$|\$)",
        text, re.IGNORECASE,
    )
    return m.group(1).strip(" -–—:*") if m else ""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def review(query: str, answer: rag.RagAnswer, k: int = 5) -> Review:
    """Reviewer: independently re-retrieve and adversarially check the answer.

    Isolated context — the reviewer gets the answer text and its OWN retrieval, not
    the writer's trace. Three checks, all grounded in the evidence:

    1. **grounded** — every product/price cited is in the retrieved set.
    2. **lead-is-a-deal** — the lead pick is a genuine DEAL, not a SUSPICIOUS trap
       or an OVERPRICED item sold as the best value.
    3. **trap-warned** — if a SUSPICIOUS trap was retrieved, the answer must flag it
       (say "avoid"/"SUSPICIOUS"), not stay silent.
    """
    items = rag.retrieve(query, k=k, use_db=_SNAPSHOT)
    by_title = {_norm(it.title): it for it in items}
    checks: dict[str, bool] = {}
    issues: list[str] = []

    # 1. grounded
    checks["grounded"] = rag.is_grounded(answer.answer, items)
    if not checks["grounded"]:
        issues.append("cites a product or price not in the retrieved evidence")

    # 2. lead pick must be a DEAL
    lead = _norm(_lead_title(answer.answer))
    lead_item = next((it for t, it in by_title.items() if lead and lead in t), None)
    checks["lead_is_a_deal"] = lead_item is not None and lead_item.verdict == "deal"
    if lead_item is not None and lead_item.verdict != "deal":
        issues.append(f"lead pick is {lead_item.verdict.upper()}, not a DEAL: {lead_item.title}")
    elif lead_item is None:
        issues.append("could not identify the lead pick in the evidence")

    # 3. if a SUSPICIOUS trap exists, it must be warned about
    traps = [it for it in items if it.verdict == "suspicious"]
    if traps:
        warned = "suspicious" in answer.answer.lower() or "avoid" in answer.answer.lower()
        checks["trap_warned"] = warned
        if not warned:
            issues.append(f"retrieved a SUSPICIOUS trap ({traps[0].title}) but did not warn about it")
    else:
        checks["trap_warned"] = True

    return Review(approved=all(checks.values()), issues=issues, checks=checks)


def orchestrate(query: str, k: int = 5, *, recommender_llm=None) -> Orchestrated:
    """Writer → Reviewer → revise-if-rejected.

    Runs the recommender, has the reviewer adversarially check it, and if the review
    fails, revises by falling back to the always-grounded deterministic answer and
    re-reviewing. Returns the final answer plus the review trail.
    """
    draft = recommend(query, k=k, llm=recommender_llm)
    r = review(query, draft, k=k)
    if r.approved:
        return Orchestrated(draft.answer, True, r, revised=False, used_llm=draft.used_llm)

    # Revise: fall back to the LLM-free deterministic answer — it is *guaranteed*
    # grounded and leads with the top DEAL, regardless of any configured key. (Note
    # `rag.answer(query, k=k)` would NOT do this once an OpenRouter key is set: it
    # would use the LLM and could reproduce the same class of mistake.)
    fixed = rag.deterministic_answer(query, k=k, use_db=_SNAPSHOT)
    r2 = review(query, fixed, k=k)
    return Orchestrated(fixed.answer, r2.approved, r2, revised=True, used_llm=False)
