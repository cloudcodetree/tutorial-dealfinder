from dealfinder.agent import Action, Agent, Tool
from dealfinder.tools import nl_to_sql


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


def test_nl_to_sql_builds_where_clause():
    sql = nl_to_sql("2-person tents under $400 from TrailLite")
    assert sql == (
        "SELECT * FROM catalog WHERE price < 400 AND capacity = 2 "
        "AND brand = 'TrailLite'"
    )
