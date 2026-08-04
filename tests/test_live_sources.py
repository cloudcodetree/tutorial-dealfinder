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
def test_bestbuy_search_maps_saleprice(monkeypatch):
    from dealfinder.live_sources import BestBuySource
    monkeypatch.setenv("BESTBUY_API_KEY", "k")
    respx.get(url__regex=r"https://api\.bestbuy\.com/v1/products.*").mock(
        return_value=httpx.Response(200, json={"products": [
            {"sku": 123, "name": "4K TV", "salePrice": 399.99, "regularPrice": 499.99,
             "url": "https://bestbuy.com/tv", "image": "http://img", "manufacturer": "Sony"},
        ]}))
    out = BestBuySource().search("4k tv")
    assert len(out) == 1
    assert out[0].price == 399.99 and out[0].source == "BestBuy:sale" and out[0].brand == "Sony"


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


@respx.mock
def test_amazon_maps_apify_actor_response(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    from dealfinder.live_sources import AmazonSource
    # The junglee/Amazon-crawler actor returns a JSON list; price is a {value,currency} object.
    respx.post(url__regex=r"https://api\.apify\.com/v2/acts/junglee~Amazon-crawler/.*").mock(
        return_value=httpx.Response(200, json=[
            {"title": "Soundcore by Anker Q20i Hybrid Active Noise Cancelling Headphones",
             "price": {"value": 39.98, "currency": "$"}, "asin": "B0CQXMXJC5", "imageUrl": "http://img/1.jpg"},
            {"title": "Euro-priced item", "price": {"value": 30.0, "currency": "€"}, "asin": "X"},  # dropped: not USD
            {"title": "No price row", "asin": "Y"},                                                 # dropped: no price
        ]))
    out = AmazonSource().search("noise cancelling headphones", limit=5)
    assert len(out) == 1                                   # euro + no-price rows filtered out
    p = out[0]
    assert p.price == 39.98 and p.currency == "USD"
    assert p.source == "Amazon" and p.brand == "Amazon"
    assert p.url == "https://www.amazon.com/dp/B0CQXMXJC5"  # URL built from ASIN
    assert p.id == "amazon-B0CQXMXJC5"


def test_amazon_off_without_token(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    from dealfinder.live_sources import AmazonSource
    assert AmazonSource().available() is False
    assert AmazonSource().search("headphones") == []
