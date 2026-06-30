"""Offline tests for live-source parsing (HTTP mocked with respx)."""
import httpx
import respx

from dealfinder.live_sources import FirecrawlSource


@respx.mock
def test_firecrawl_keeps_priced_results_skips_reviews(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test")
    respx.post("https://api.firecrawl.dev/v1/search").mock(
        return_value=httpx.Response(200, json={"data": [
            {"title": "Buds", "url": "https://www.bestbuy.com/buds", "description": "Great buds $99.99 today"},
            {"title": "Best of 2026", "url": "https://rtings.com/best", "description": "our pick at $35"},
            {"title": "No price", "url": "https://shop.example/x", "description": "no price mentioned"},
        ]})
    )
    out = FirecrawlSource().search("buds")
    assert len(out) == 1                      # review domain + price-less dropped
    assert out[0].price == 99.99
    assert "bestbuy.com" in out[0].source


def test_firecrawl_off_without_key(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    assert FirecrawlSource().available() is False
    assert FirecrawlSource().search("x") == []
