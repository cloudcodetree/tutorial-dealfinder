"""RAG over the REAL snapshot — offline, deterministic, no network.

The fastembed model runs from its committed local cache (same convention as
test_search.py), so these tests never touch the network. Every value is pinned
against the frozen snapshot ``data/snapshots/electronics-2026-07.json`` and the
spec §9.1 hero-cast facts.
"""
from fastapi.testclient import TestClient

from dealfinder.rag import (
    RetrievedItem,
    answer,
    build_context,
    evaluate_rag,
    is_grounded,
    retrieve,
)

QUERY = "noise cancelling headphones under $150"

# retrieve() now defaults to the deterministic value-reranked cached path
# (pgvector is opt-in via use_db=True), so these tests reproduce regardless of
# whether a dev DATABASE_URL is exported — no env fixture needed.


# ---------------------------------------------------------------------------
# retrieve — real snapshot items, hero cast in the expected slots.
# ---------------------------------------------------------------------------
def test_retrieve_surfaces_real_items_with_anker_near_top():
    items = retrieve(QUERY, k=5)
    assert len(items) == 5
    assert all(isinstance(it, RetrievedItem) for it in items)

    titles = [it.title for it in items]
    # The honest Anker Q20i deal is the top pick (value rerank floats it up).
    assert "Anker Soundcore Q20i" in titles[0]
    # Its two-signal verdict is DEAL, and it's the real $44.99 snapshot price.
    assert items[0].verdict == "deal"
    assert items[0].price == 44.99

    # The Bose QC45 trap is retrieved and flagged SUSPICIOUS at its real $46.00.
    bose = next(it for it in items if "QuietComfort 45" in it.title)
    assert bose.verdict == "suspicious"
    assert bose.price == 46.00


def test_build_context_is_numbered_and_grounds_on_real_prices():
    items = retrieve(QUERY, k=5)
    ctx = build_context(items)
    assert ctx.startswith("[1] Anker Soundcore Q20i")
    assert "$44.99" in ctx and "$46.00" in ctx
    assert "[DEAL]" in ctx and "[SUSPICIOUS]" in ctx


# ---------------------------------------------------------------------------
# answer — deterministic (no-LLM) path is grounded and names the hero cast.
# ---------------------------------------------------------------------------
def test_deterministic_answer_is_grounded_and_names_the_cast():
    a = answer(QUERY, k=5)  # no OPENROUTER key in test env → deterministic path
    assert a.used_llm is False
    assert a.grounded is True

    # Names the Anker Q20i DEAL and flags the Bose QC45 SUSPICIOUS trap.
    assert "Anker Soundcore Q20i" in a.answer
    assert "$44.99" in a.answer
    assert "Bose QuietComfort 45" in a.answer
    assert "$46.00" in a.answer
    assert "SUSPICIOUS" in a.answer

    # Sources are the retrieved ids the answer actually referenced.
    items = retrieve(QUERY, k=5)
    retrieved_ids = {it.id for it in items}
    assert a.sources and set(a.sources) <= retrieved_ids


# ---------------------------------------------------------------------------
# is_grounded — catches a hallucinated product not in the retrieved set.
# ---------------------------------------------------------------------------
def test_is_grounded_rejects_hallucinated_product():
    items = retrieve(QUERY, k=5)
    # A product (and price) that is NOT in the retrieved set.
    halluc = "Buy the Sennheiser Momentum 4 at $199.00 — it's the best pick."
    assert is_grounded(halluc, items) is False

    # A real product with a fabricated price is also a hallucination.
    bad_price = "The Anker Soundcore Q20i at $9.99 is the steal of the year."
    assert is_grounded(bad_price, items) is False

    # A faithful answer citing a real retrieved product + price is grounded.
    good = "The Anker Soundcore Q20i at $44.99 is the best value."
    assert is_grounded(good, items) is True


# ---------------------------------------------------------------------------
# answer — injected fake LLM client is used and still passes grounding.
# ---------------------------------------------------------------------------
class _FakeLLM:
    """A stand-in LLM that answers strictly from the retrieved listings.

    ``answer()`` treats any object with ``available()`` + ``chat()`` as the client,
    so the LLM branch is exercised with zero network calls.
    """

    def __init__(self):
        self.called = False

    def available(self) -> bool:
        return True

    def chat(self, messages, temperature=0):
        self.called = True
        return (
            "Top pick: Anker Soundcore Q20i at $44.99 — a genuine DEAL. "
            "Avoid the Bose QuietComfort 45 at $46.00, flagged SUSPICIOUS."
        )


def test_answer_uses_injected_llm_and_stays_grounded():
    fake = _FakeLLM()
    a = answer(QUERY, k=5, llm=fake)
    assert fake.called is True
    assert a.used_llm is True
    assert a.grounded is True
    # It only cites real retrieved items.
    items = retrieve(QUERY, k=5)
    assert set(a.sources) <= {it.id for it in items}


def test_injected_llm_hallucination_is_flagged_not_grounded():
    class Hallucinator:
        def available(self):
            return True

        def chat(self, messages, temperature=0):
            # Invents a product + price that were never retrieved.
            return "Best pick: the Bose QuietComfort Ultra at $129.00."

    a = answer(QUERY, k=5, llm=Hallucinator())
    assert a.used_llm is True
    assert a.grounded is False  # faithfulness check catches the invention


# ---------------------------------------------------------------------------
# evaluate_rag — grounding eval over golden queries: 100% faithful.
# ---------------------------------------------------------------------------
def test_evaluate_rag_is_fully_grounded():
    report = evaluate_rag()
    assert report["faithfulness_rate"] == 1.0
    assert report["n"] == 2
    for row in report["results"]:
        assert row["grounded"] is True
        assert row["hero_surfaced"] is True
    # The headphones golden query surfaces the Anker Q20i as the top DEAL.
    hp = report["results"][0]
    assert "Anker Soundcore Q20i" in hp["expected_hero"]
    assert hp["top_verdict"] == "deal"


# ---------------------------------------------------------------------------
# serve — GET /ask returns the RagAnswer JSON; existing routes still work.
# ---------------------------------------------------------------------------
def test_ask_endpoint_returns_grounded_rag_answer():
    from dealfinder.serve import app

    client = TestClient(app)
    r = client.get("/ask", params={"q": QUERY, "k": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == QUERY
    assert "Anker Soundcore Q20i" in body["answer"]
    assert body["grounded"] is True
    assert body["used_llm"] is False
    assert body["sources"]

    # An existing route is unaffected.
    assert client.get("/healthz").json()["status"] == "ok"
