"""A DealFinder agent answering a goal by chaining tools.

The policy here is rule-based so it runs offline and deterministically; in
production it's an LLM (LangGraph) reading the same trace. Either way you get a
ReAct trace: think → act → observe → … → answer.

Run:  python -m dealfinder.run_agent
"""
from __future__ import annotations

from .agent import Action, Agent, Tool
from .deal import deal_score
from .dealmodel import LinearModel
from .features import feature_matrix
from .tools import build_db, load_catalog, nl_to_sql, run_sql

GOAL = "find me a good 2-person tent under $400"


def main() -> None:
    catalog = load_catalog()
    con = build_db(catalog)
    X = feature_matrix(catalog)
    model = LinearModel().fit(X, [p.price for p in catalog])
    fair = {p.id: float(fp) for p, fp in zip(catalog, model.predict(X))}

    def sql_search(question):
        sql = nl_to_sql(question)
        return {"sql": sql, "rows": run_sql(con, sql)}

    def rank_deals(ids):
        scored = [{"id": i, "price": fair_row(i), "deal": deal_score(price_of(i), fair[i])} for i in ids]
        return sorted(scored, key=lambda r: -r["deal"])

    price_of = {p.id: p.price for p in catalog}.__getitem__
    fair_row = lambda i: round(price_of(i), 0)  # noqa: E731

    tools = [Tool("sql_search", sql_search, "NL → SQL over the catalog"),
             Tool("rank_deals", rank_deals, "rank ids by deal score")]

    def policy(goal, trace):
        if len(trace) == 0:
            return Action("Translate the request into SQL and filter the catalog", "sql_search", {"question": goal})
        if len(trace) == 1:
            ids = [r["id"] for r in trace[0].observation["rows"]]
            return Action("Rank those matches by how good a deal each is", "rank_deals", {"ids": ids})
        best = trace[1].observation[0]
        return Action("Pick the best-value match and answer", None,
                      answer=f'{best["id"]} at ${price_of(best["id"]):.0f} ({best["deal"] * 100:.0f}% under fair)')

    answer, trace = Agent(tools, policy).run(GOAL)

    print(f'goal: "{GOAL}"\n')
    for n, s in enumerate(trace, 1):
        if s.tool == "sql_search":
            print(f"step {n} · think: {s.thought}")
            print(f'         act:   sql_search → {s.observation["sql"]}')
            print(f"         obs:   {len(s.observation['rows'])} tents match")
        elif s.tool == "rank_deals":
            top = s.observation[0]
            print(f"step {n} · think: {s.thought}")
            print(f"         act:   rank_deals({len(s.args['ids'])} ids)")
            print(f"         obs:   best = {top['id']} ({top['deal'] * 100:.0f}% under fair)")
        else:
            print(f"step {n} · answer: {s.observation}")
    print(f"\n✓ {answer}")


if __name__ == "__main__":
    main()
