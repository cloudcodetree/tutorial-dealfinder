"""Multi-agent orchestration: writer → reviewer → revise.

Offline + deterministic. The adversarial writer is an injected fake LLM, exactly
like rag.py's tests — no network.
"""
from dealfinder import orchestrate as orch

QUERY = "noise cancelling headphones under $150"


class _TrapWriter:
    """A writer that recommends the $46 Bose QC45 (SUSPICIOUS) as the best value."""

    def available(self):
        return True

    def chat(self, messages, temperature=0):
        return (
            "Best value: Bose QuietComfort 45 Wireless Noise Cancelling Headphones "
            "at $46.00 — an incredible deal."
        )


def test_reviewer_approves_a_good_grounded_recommendation():
    o = orch.orchestrate(QUERY)  # deterministic writer leads with the Anker DEAL
    assert o.approved is True
    assert o.revised is False
    assert o.review.checks == {"grounded": True, "lead_is_a_deal": True, "trap_warned": True}
    assert "Anker Soundcore Q20i" in o.answer


def test_reviewer_rejects_a_trap_recommendation():
    draft = orch.recommend(QUERY, llm=_TrapWriter())
    r = orch.review(QUERY, draft)
    assert r.approved is False
    assert r.checks["lead_is_a_deal"] is False        # lead is SUSPICIOUS
    assert any("SUSPICIOUS" in issue for issue in r.issues)


def test_orchestrator_revises_a_rejected_draft_to_a_grounded_answer():
    o = orch.orchestrate(QUERY, recommender_llm=_TrapWriter())
    assert o.revised is True                           # the trap draft was rejected
    assert o.approved is True                          # the revision passes review
    assert "Anker Soundcore Q20i" in o.answer          # leads with the real DEAL
    assert "$44.99" in o.answer


def test_reviewer_catches_a_hallucinated_price():
    class Hallucinator:
        def available(self):
            return True

        def chat(self, messages, temperature=0):
            return "Best value: Anker Soundcore Q20i at $9.99 — unbeatable."

    draft = orch.recommend(QUERY, llm=Hallucinator())
    r = orch.review(QUERY, draft)
    assert r.checks["grounded"] is False               # $9.99 was never retrieved
    assert r.approved is False
