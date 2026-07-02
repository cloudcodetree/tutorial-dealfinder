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


@respx.mock
def test_shopify_filters_catalog_by_query(monkeypatch):
    from dealfinder.live_sources import ShopifySource
    monkeypatch.setenv("SHOPIFY_STORES", "teststore.com")
    respx.get("https://teststore.com/products.json").mock(return_value=httpx.Response(200, json={"products": [
        {"id": 1, "title": "Dark Roast Coffee", "handle": "dark-roast", "vendor": "Store",
         "product_type": "Coffee", "tags": ["beans"], "variants": [{"price": "14.99"}], "images": [{"src": "http://img"}]},
        {"id": 2, "title": "Plain T-Shirt", "handle": "tee", "vendor": "Store",
         "tags": [], "variants": [{"price": "20.00"}], "images": []},
    ]}))
    out = ShopifySource().search("coffee")
    assert len(out) == 1                       # only the matching product
    assert out[0].price == 14.99 and "teststore.com" in out[0].source


@respx.mock
def test_ebay_oauth_then_browse_search(monkeypatch):
    from dealfinder.live_sources import EbaySource
    monkeypatch.setenv("EBAY_APP_ID", "chrishar-DealFind-SBX-abc")
    monkeypatch.setenv("EBAY_CERT_ID", "SBX-secret")
    respx.post("https://api.sandbox.ebay.com/identity/v1/oauth2/token").mock(
        return_value=httpx.Response(200, json={"access_token": "t", "expires_in": 7200, "token_type": "App"}))
    respx.get("https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search").mock(
        return_value=httpx.Response(200, json={"itemSummaries": [
            {"itemId": "v1|123|0", "title": "Laptop", "price": {"value": "659.99", "currency": "USD"},
             "condition": "New", "itemWebUrl": "https://ebay/x", "image": {"imageUrl": "http://img"}},
        ]}))
    out = EbaySource().search("laptop")
    assert len(out) == 1
    assert out[0].price == 659.99 and out[0].source == "eBay:New"
