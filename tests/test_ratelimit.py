"""Per-instance rate limits for the anonymous routes. /ask is limited hardest."""

from dealfinder import ratelimit


def test_ask_is_limited_hardest():
    t = [0.0]
    lim = ratelimit.Limiter(clock=lambda: t[0])
    assert all(lim.check("/ask", "1.2.3.4") is None for _ in range(5))
    assert lim.check("/ask", "1.2.3.4") > 0
    assert lim.check("/ask", "5.6.7.8") is None          # other clients unaffected
    t[0] = 61.0
    assert lim.check("/ask", "1.2.3.4") is None          # window slides


def test_search_stream_shares_the_search_limit():
    lim = ratelimit.Limiter(clock=lambda: 0.0)
    assert all(lim.check("/search/stream", "ip") is None for _ in range(30))
    assert lim.check("/search/stream", "ip") > 0


def test_unlisted_paths_are_not_limited():
    lim = ratelimit.Limiter()
    assert all(lim.check("/watchlist", "x") is None for _ in range(100))


def test_limiter_memory_is_bounded():
    t = [0.0]
    lim = ratelimit.Limiter(clock=lambda: t[0], max_keys=100)
    for i in range(100):
        assert lim.check("/ask", f"10.0.0.{i}") is None
    t[0] = 61.0
    assert lim.check("/ask", "10.0.1.1") is None
    assert len(lim) <= 2


def test_retry_after_counts_down_to_the_oldest_request():
    t = [0.0]
    lim = ratelimit.Limiter(clock=lambda: t[0])
    for _ in range(5):
        lim.check("/ask", "ip")
    t[0] = 20.0
    assert lim.check("/ask", "ip") == 40.0
