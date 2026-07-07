from dealfinder.agent import Action, Agent, Tool
from dealfinder.tools import build_db, load_catalog, nl_to_sql, run_sql


def _scripted(script):
    return lambda goal, trace: script[len(trace)]


def test_agent_runs_tool_then_finishes():
    seen = []
    tools = [Tool("add", lambda a, b: seen.append((a, b)) or (a + b))]
    script = [Action("use add", "add", {"a": 2, "b": 3}), Action("done", None, answer=5)]
    answer, trace = Agent(tools, _scripted(script)).run("sum 2 and 3")
    assert answer == 5
    assert trace[0].tool == "add" and trace[0].observation == 5
    assert seen == [(2, 3)]


def test_hitl_blocks_unapproved_action():
    tools = [Tool("purge", lambda: "gone", requires_approval=True)]
    script = [Action("purge it", "purge", {}), Action("stop", None, answer="halted")]
    answer, trace = Agent(tools, _scripted(script), approve=lambda name, args: False).run("clean up")
    assert "BLOCKED" in str(trace[0].observation)
    assert answer == "halted"


def test_nl_to_sql_builds_electronics_where_clause():
    sql = nl_to_sql("find a good noise-cancelling headphone under $120 from Sony")
    assert sql == (
        "SELECT * FROM catalog WHERE price < 120 AND category = 'audio' "
        "AND title LIKE '%Sony%' AND title LIKE '%headphone%'"
    )


def test_nl_to_sql_runs_against_the_real_catalog():
    con = build_db(load_catalog())
    rows = run_sql(con, nl_to_sql("noise-cancelling headphone under $120"))
    assert rows                                   # the query returns real audio items
    assert all(r["category"] == "audio" and r["price"] < 120 for r in rows)
    assert all("headphone" in r["title"].lower() for r in rows)
    # the honest Anker deal is in the result set
    assert any("Q20i" in r["title"] for r in rows)
