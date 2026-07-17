"""Context engineering: budgeting, ordering, and compaction over real deals.

Token counts come from the cached bge tokenizer, so they are exact and offline.
"""
from dealfinder import context as ctx
from dealfinder import rag

QUERY = "noise cancelling headphones under $150"


def test_count_tokens_matches_the_model_number_explosion():
    # The Part 2 lesson: model-number strings explode into many tokens.
    assert ctx.count_tokens("Sony WH-1000XM5 Wireless Noise Cancelling Headphones") == 16


def test_pack_deals_drops_the_tail_to_fit_a_budget():
    items = rag.retrieve(QUERY, k=20)
    packed = ctx.pack_deals(items, budget_tokens=256)
    assert packed.tokens <= 256
    assert len(packed.included) + len(packed.dropped) == len(items)
    assert len(packed.dropped) > 0            # k=20 does NOT fit in 256 tokens
    # Included items are the top-ranked prefix (greedy, in order).
    assert packed.included[0].title == items[0].title


def test_lost_in_the_middle_puts_the_best_at_the_edges():
    items = rag.retrieve(QUERY, k=5)
    reordered = ctx.lost_in_the_middle(items)
    assert set(id(i) for i in reordered) == set(id(i) for i in items)  # same set
    assert reordered[0] is items[0]           # best pick leads
    assert reordered[-1] is items[1]          # 2nd best sits last
    # The weakest-ranked item is buried in the middle, not at an edge.
    assert items[-1] not in (reordered[0], reordered[-1])


def test_compact_history_preserves_intent_and_shrinks_tokens():
    turns = [
        "user: noise cancelling headphones under $150",
        "assistant: Best value: Anker Soundcore Q20i at $44.99.",
        "user: what about wireless earbuds instead",
        "assistant: JBL Tune 770NC at $89.95 leads.",
        "user: only ones with a mic",
        "assistant: The Anker Q20i and JBL 770NC both have mics.",
    ]
    c = ctx.compact_history(turns, keep_recent=2)
    assert c.tokens_after < c.tokens_before          # smaller
    assert "earlier queries:" in c.text
    assert "noise cancelling headphones under $150" in c.text  # intent kept
    assert turns[-1] in c.text                        # recent turn verbatim
    assert "Best value" not in c.text                 # old assistant prose dropped


def test_compact_history_noop_when_short():
    turns = ["user: cheap monitor", "assistant: MSI MP273U at $159.99."]
    c = ctx.compact_history(turns, keep_recent=2)
    assert c.tokens_after == c.tokens_before
