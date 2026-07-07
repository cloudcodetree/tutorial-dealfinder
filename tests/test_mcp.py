from dealfinder import mcp_server


def _id(needle):
    return next(p.id for p in mcp_server._catalog if needle.lower() in p.title.lower())


def test_server_registers_expected_tools():
    names = {t.name for t in mcp_server.mcp._tool_manager.list_tools()}
    assert names == {"score_deal", "recommend", "search_deals"}


def test_score_deal_flags_the_anker_as_a_deal():
    out = mcp_server.score_deal(_id("Anker Soundcore Q20i"))
    assert out["price"] == 44.99
    assert out["verdict"] == "deal"          # the honest hero deal
    assert out["median_signal"] > 0.70


def test_score_deal_flags_the_bose_trap_as_suspicious():
    out = mcp_server.score_deal(_id("Bose QuietComfort 45"))
    assert out["verdict"] == "suspicious"    # median says steal; residual guards it
    assert out["residual_frac"] > 0.70


def test_recommend_returns_similar_real_audio_items():
    recs = mcp_server.recommend(_id("Sony WH-1000XM5 Wireless Headphones"), k=2)
    assert len(recs) == 2
    assert all("WH-1000XM5" not in r["id"] or r["id"] != _id("Sony WH-1000XM5 Wireless Headphones") for r in recs)
    # the premium Sony sibling XM6 is in the neighbourhood
    assert any("WH-1000XM" in r["title"] for r in recs)


def test_catalog_stats_reflect_the_270_item_snapshot():
    stats = mcp_server.catalog_stats()
    assert "270" in stats and "11 categories" in stats
