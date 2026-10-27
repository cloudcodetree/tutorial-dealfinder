"""Offline SSE test (Part 31 backend).

Deterministic: we swap the live sources for a snapshot-backed stub, so the
/search/stream endpoint streams without touching the network. Live use pulls
from the learner's configured real sources; the streaming shape is identical.
"""
from fastapi.testclient import TestClient

import dealfinder.serve as serve
from dealfinder.schema import Product
from dealfinder.serve import app

client = TestClient(app)


class _StubSource:
    name = "Stub"

    def available(self):
        return True

    def search(self, query, limit=15):
        return [
            Product(id="s1", title="Sony WH-1000XM5", brand="Costco",
                    category="audio", price=162.97, url="", source="BestBuy"),
            Product(id="s2", title="Anker Soundcore Q20i", brand="Anker",
                    category="audio", price=44.99, url="", source="BestBuy:sale"),
        ]


def test_stream_emits_data_events_and_done(monkeypatch):
    monkeypatch.setattr(serve, "enabled_sources", lambda: [_StubSource()])

    with client.stream("GET", "/search/stream?q=noise+cancelling+headphones") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())

    # at least one data frame, and a terminal done event
    assert body.count("data:") >= 2
    assert "event: results" in body
    assert "event: done" in body
    # the streamed payload carries the real snapshot hero item
    assert "Sony WH-1000XM5" in body
    assert "162.97" in body


def test_stream_still_terminates_when_no_sources(monkeypatch):
    monkeypatch.setattr(serve, "enabled_sources", lambda: [])
    with client.stream("GET", "/search/stream?q=whatever") as r:
        body = "".join(r.iter_text())
    # no results, but the stream still closes cleanly with a done event
    assert "event: done" in body
    assert '"count": 0' in body


class _MixedSource:
    """A source whose rows include one a store's terms forbid mixing."""
    name = "Mixed"

    def available(self):
        return True

    def search(self, query, limit=15):
        return [
            Product(id="bb1", title="Sony WH-1000XM5", brand=None, category="audio", price=100.0, url="", source="BestBuy"),
            Product(id="bb2", title="Bose QC45", brand=None, category="audio", price=200.0, url="", source="BestBuy"),
            Product(id="eb1", title="EBAY ONLY", brand=None, category="audio", price=1.0, url="", source="eBay:Used"),
        ]


def _stream_body(path):
    with client.stream("GET", path) as r:
        return "".join(r.iter_text())


def _done(body):
    import json
    frame = body.split("event: done")[1].split("data: ", 1)[1].split("\n", 1)[0]
    return json.loads(frame)


def test_stream_follows_the_license_rules(monkeypatch):
    from dealfinder import licensing
    monkeypatch.setattr(serve, "enabled_sources", lambda: [_MixedSource()])
    body = _stream_body("/search/stream?q=headphones")
    assert "EBAY ONLY" not in body
    done = _done(body)
    assert done["median_price"] == 150.0 and done["count"] == 2
    assert done["attribution"] == [licensing.POLICIES["BestBuy"].attribution]


def test_stream_shows_no_median_in_check_mode(monkeypatch):
    monkeypatch.setenv("DEALFINDER_VERDICT_MODE", "check")
    monkeypatch.setattr(serve, "enabled_sources", lambda: [_MixedSource()])
    assert _done(_stream_body("/search/stream?q=headphones"))["median_price"] is None
