import httpx
import respx

from dealfinder.sources import ApiSource


@respx.mock
def test_api_source_normalizes():
    respx.get("https://api.test/search").mock(
        return_value=httpx.Response(200, json={
            "items": [{
                "id": "abc", "title": "Widget", "brand": "Acme",
                "category": "misc", "price": 12.5, "url": "https://ex/abc",
            }]
        })
    )
    items = list(ApiSource("https://api.test", "k").products())
    assert items[0].id == "abc"
    assert items[0].source == "api"
    assert items[0].price == 12.5
