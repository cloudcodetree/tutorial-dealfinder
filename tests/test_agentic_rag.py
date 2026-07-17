"""Agentic RAG: retrieval as a repeated, judged tool call.

Offline + deterministic against the frozen snapshot: the sufficiency gate is a
pure function of the retrieved verdicts, and the reformulator expands with
corpus-mined capability terms, so the whole trajectory is reproducible.
"""
from dealfinder import agentic_rag as ar
from dealfinder import rag


def test_sufficiency_flags_a_trap_dominated_set():
    # A vague query's weak set: 1 DEAL, 2 SUSPICIOUS traps → insufficient.
    items = rag.retrieve("cheap wireless earbuds", k=5)
    ok, reason = ar.sufficiency(items)
    assert ok is False
    assert "DEAL" in reason or "trap" in reason.lower()


def test_sufficiency_accepts_a_strong_deal_set():
    # The sharpened query surfaces multiple honest DEALs, top is a DEAL, no traps.
    items = rag.retrieve("wireless earbuds noise cancelling deal", k=5)
    ok, reason = ar.sufficiency(items)
    assert ok is True
    assert "DEAL" in reason


def test_reformulate_expands_with_a_corpus_capability_term():
    prods, _ = ar.load_catalog_embeddings()
    lexicon = ar._capability_lexicon(prods)
    items = rag.retrieve("cheap wireless earbuds", k=5)
    new_q, phrase = ar.reformulate("wireless earbuds", items, lexicon, tried=set())
    # It drops nothing it needs, appends a real corpus phrase + value intent.
    assert phrase is not None
    assert new_q.endswith("deal")
    assert phrase in lexicon[items[0].category]


def test_monitor_query_iterates_then_converges():
    # "cheap monitor" is weak twice (top OVERPRICED, then too thin) and converges
    # on the third hop to a strong, in-category DEAL set.
    res = ar.agentic_answer("cheap monitor")
    assert len(res.hops) == 3
    assert res.hops[0].sufficient is False
    assert res.hops[-1].sufficient is True
    assert res.grounded is True
    assert "MSI Pro MP273U" in res.answer  # the real 4K monitor DEAL at $159.99
    assert "$159.99" in res.answer


def test_earbuds_query_converges_in_two_hops():
    res = ar.agentic_answer("cheap wireless earbuds")
    assert len(res.hops) == 2
    assert res.hops[0].sufficient is False       # 1 DEAL, 2 SUSPICIOUS
    assert res.hops[1].sufficient is True        # 2 DEALs, 0 traps
    assert res.hops[1].query == "wireless earbuds noise cancelling deal"
    assert res.grounded is True


def test_answer_stays_grounded_over_the_final_hop():
    # Whatever the trajectory, the final answer only cites retrieved listings.
    res = ar.agentic_answer("cheap monitor")
    final_items = rag.retrieve(res.hops[-1].query, k=5)
    assert rag.is_grounded(res.answer, final_items) is True
