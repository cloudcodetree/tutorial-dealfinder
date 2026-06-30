from dealfinder import mcp_server


def test_server_registers_expected_tools():
    names = {t.name for t in mcp_server.mcp._tool_manager.list_tools()}
    assert names == {"score_deal", "recommend", "search_deals"}


def test_score_deal_tool_returns_deal_info():
    out = mcp_server.score_deal("tent-03")
    assert out["id"] == "tent-03"
    assert out["deal_score"] > 0.15   # tent-03 is a known underpriced deal


def test_recommend_tool_excludes_self():
    recs = mcp_server.recommend("tent-00", k=2)
    assert len(recs) == 2
    assert all(r["id"] != "tent-00" for r in recs)
