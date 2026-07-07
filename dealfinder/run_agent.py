"""A DealFinder agent answering a goal by chaining tools over the real catalog.

The policy here is rule-based so it runs offline and deterministically; in
production it's an LLM (LangGraph) reading the same trace. Either way you get a
ReAct trace: think → act → observe → … → answer.

Goal: "find a good noise-cancelling headphone under $120" → SQL-filter the real
snapshot, then rank the matches by the two-signal deal score so the honest Anker
Q20i wins over the too-good-to-be-true Bose-QC45 trap.

Run:  python -m dealfinder.run_agent
"""
from __future__ import annotations

from .agent import Action, Agent, Tool
from .dealmodel import LinearModel
from .dealscore import fair_price, median_signal, residual_fraction
from .features import feature_matrix, featurize
from .snapshot import load_snapshot
from .tools import build_db, load_catalog, nl_to_sql, run_sql

GOAL = "find a good noise-cancelling headphone under $120"


def main() -> None:
    catalog = load_catalog()
    con = build_db(catalog)
    by_id = {p.id: p for p in catalog}
    medians = {r["id"]: r["median_price_at_capture"] for r in load_snapshot()}

    # Per-category price models for the residual guard.
    by_cat: dict[str, list] = {}
    for p in catalog:
        by_cat.setdefault(p.category, []).append(p)
    models = {
        c: LinearModel().fit(feature_matrix(ps), [p.price for p in ps])
        for c, ps in by_cat.items() if len(ps) >= 3
    }

    def deal_of(pid: str) -> float:
        p = by_id[pid]
        m = median_signal(p.price, medians.get(pid, 0.0))
        model = models.get(p.category)
        if model is None:
            return m
        rf = residual_fraction(p.price, fair_price(model, featurize(p)))
        return m - 1.0 if (m >= 0.15 and rf > 0.70) else m  # demote traps

    def sql_search(question):
        sql = nl_to_sql(question)
        return {"sql": sql, "rows": run_sql(con, sql)}

    def rank_deals(ids):
        scored = [{"id": i, "price": by_id[i].price, "deal": deal_of(i)} for i in ids]
        return sorted(scored, key=lambda r: -r["deal"])

    tools = [Tool("sql_search", sql_search, "NL → SQL over the catalog"),
             Tool("rank_deals", rank_deals, "rank ids by two-signal deal score")]

    def policy(goal, trace):
        if len(trace) == 0:
            return Action("Translate the request into SQL and filter the catalog", "sql_search", {"question": goal})
        if len(trace) == 1:
            ids = [r["id"] for r in trace[0].observation["rows"]]
            return Action("Rank those matches by how good a deal each is", "rank_deals", {"ids": ids})
        best = trace[1].observation[0]
        p = by_id[best["id"]]
        return Action("Pick the best-value match and answer", None,
                      answer=f'{p.title} at ${p.price:.2f} ({best["deal"] * 100:.0f}% under median)')

    answer, trace = Agent(tools, policy).run(GOAL)

    print(f'goal: "{GOAL}"\n')
    for n, s in enumerate(trace, 1):
        if s.tool == "sql_search":
            print(f"step {n} · think: {s.thought}")
            print(f'         act:   sql_search → {s.observation["sql"]}')
            print(f"         obs:   {len(s.observation['rows'])} items match")
        elif s.tool == "rank_deals":
            top = s.observation[0]
            print(f"step {n} · think: {s.thought}")
            print(f"         act:   rank_deals({len(s.args['ids'])} ids)")
            print(f"         obs:   best = {by_id[top['id']].title[:40]} ({top['deal'] * 100:.0f}% under median)")
        else:
            print(f"step {n} · answer: {s.observation}")
    print(f"\n{answer}")


if __name__ == "__main__":
    main()
