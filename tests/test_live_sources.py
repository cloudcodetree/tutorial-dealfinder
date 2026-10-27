"""Offline tests for live-source parsing (HTTP mocked with respx)."""
import httpx
import pytest
import respx

from dealfinder import live_sources
from dealfinder.live_sources import BestBuySource, EbaySource, FirecrawlSource


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
    assert out[0].sku == "123" and out[0].regular_price == 499.99


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


def test_ebay_is_not_a_live_source():
    assert all(s.name != "eBay" for s in live_sources.LIVE_SOURCES)


def test_enabled_sources_from_env(monkeypatch):
    monkeypatch.setenv("DEALFINDER_SOURCES", "bestbuy")
    assert [s.name for s in live_sources.enabled_sources()] == ["BestBuy"]


def test_enabled_sources_default_is_every_course_source(monkeypatch):
    monkeypatch.delenv("DEALFINDER_SOURCES", raising=False)
    assert live_sources.enabled_sources() == live_sources.LIVE_SOURCES


@pytest.mark.parametrize("names, msg", [("BestBuy,eBay", "ebay_box"), ("Walmart", "unknown source")])
def test_enabled_sources_rejects_bad_names(names, msg):
    with pytest.raises(ValueError, match=msg):
        live_sources.enabled_sources(names)


@respx.mock
def test_ebay_sends_no_affiliate_context(monkeypatch):
    monkeypatch.setenv("EBAY_APP_ID", "chrishar-DealFind-SBX-abc")
    monkeypatch.setenv("EBAY_CERT_ID", "SBX-secret")
    monkeypatch.setenv("EBAY_CAMPAIGN_ID", "123")
    respx.post("https://api.sandbox.ebay.com/identity/v1/oauth2/token").mock(
        return_value=httpx.Response(200, json={"access_token": "t", "expires_in": 7200, "token_type": "App"}))
    search_route = respx.get("https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search").mock(
        return_value=httpx.Response(200, json={"itemSummaries": [
            {"itemId": "v1|9|0", "title": "Laptop", "price": {"value": "100.00", "currency": "USD"},
             "condition": "Used", "itemAffiliateWebUrl": "https://aff/x", "itemWebUrl": "https://ebay/x"},
        ]}))
    out = EbaySource().search("laptop")
    assert "X-EBAY-C-ENDUSERCTX" not in search_route.calls.last.request.headers
    assert out[0].url == "https://ebay/x"


def _bestbuy_skus(request):
    """Answer a products(sku in(...)) lookup with skus 1 and 2 only."""
    known = {"1": "Thing One", "2": "Thing Two"}
    asked = request.url.path.split("sku in(")[-1].split(")")[0].split(",")
    return httpx.Response(200, json={"products": [
        {"sku": int(s), "name": known[s], "salePrice": 10.0 * int(s), "regularPrice": 20.0,
         "url": f"https://bestbuy.com/{s}", "image": None, "manufacturer": "B"} for s in asked if s in known]})


@respx.mock
def test_lookup_skus_batches_and_maps(monkeypatch):
    monkeypatch.setenv("BESTBUY_API_KEY", "k")
    route = respx.get(url__regex=r"https://api\.bestbuy\.com/v1/products\(sku.*").mock(side_effect=_bestbuy_skus)
    found = BestBuySource().lookup_skus(["1", "2", "3", "2"])
    assert set(found) == {"1", "2"} and route.call_count == 1 and found["1"].sku == "1"


@respx.mock
def test_lookup_skus_splits_batches_of_100_and_paces_them(monkeypatch):
    monkeypatch.setenv("BESTBUY_API_KEY", "k")
    waits = []
    monkeypatch.setattr(live_sources.time, "sleep", waits.append)
    route = respx.get(url__regex=r"https://api\.bestbuy\.com/v1/products\(sku.*").mock(
        return_value=httpx.Response(200, json={"products": []}))
    assert BestBuySource().lookup_skus([str(i) for i in range(1, 151)]) == {}
    assert route.call_count == 2 and waits and min(waits) >= 0.2


def test_lookup_skus_rejects_non_digit_skus(monkeypatch):
    monkeypatch.setenv("BESTBUY_API_KEY", "k")
    with pytest.raises(ValueError):
        BestBuySource().lookup_skus(["123)&apiKey=x"])


def test_lookup_skus_without_a_key_is_empty(monkeypatch):
    monkeypatch.delenv("BESTBUY_API_KEY", raising=False)
    assert BestBuySource().lookup_skus(["1"]) == {}


@respx.mock
def test_lookup_skus_failure_is_not_gone(monkeypatch):
    monkeypatch.setenv("BESTBUY_API_KEY", "k")
    respx.get(url__regex=r"https://api\.bestbuy\.com/v1/products\(sku.*").mock(return_value=httpx.Response(500))
    with pytest.raises(RuntimeError, match="bestbuy lookup failed: 500"):
        BestBuySource().lookup_skus(["1"])
