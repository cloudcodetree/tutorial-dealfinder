from dealfinder.sources import ScraperSource


def test_scraper_parses_fixture():
    items = list(ScraperSource(["data/fixtures/listing.html"], "https://shop.ex").products())
    p = items[0]
    assert p.id == "rr2"
    assert p.brand == "RidgeRunner"
    assert p.price == 232.0
    assert p.source == "scrape"
