"""Delete licensed rows before their store's age limit, and unstorable rows at once.

Best Buy allows its data to be cached for at most 72 hours (licensing.py). The
scheduled `dealfinder-pages` job runs this every 12 hours, so a row goes once it
is older than ``max_age_s - RETENTION_MARGIN_S``. The margin covers two run
intervals plus an hour, so a Best Buy row is gone before 72 hours even when one
run fails: 47 h + 2 × 12 h = 71 h. For Best Buy the cut-off is 47 hours. A row
whose source has no policy, or may not be stored, goes at any age.

Watchlist rows go by the same rule, keyed on ``last_checked_at``: a watched
item's title and price are the store's content too. The daily re-price job
refreshes ``last_checked_at`` only after a successful lookup, so a watch expires
when the store dropped the SKU or about two days of lookups failed.

Runs as one `db.job_scope` transaction: ``python -m dealfinder.retention``.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

from . import db
from .licensing import POLICIES

RETENTION_MARGIN_S = 25 * 3600  # 2 × 12 h purge interval + 1 h

_PURGE = """
    DELETE FROM dealfinder.{table} t
    WHERE NOT EXISTS (SELECT 1 FROM unnest(%(keys)s::text[]) AS k(key)
                      WHERE k.key = split_part(t.source, ':', 1))
       OR EXISTS (SELECT 1 FROM unnest(%(keys)s::text[], %(cutoffs)s::timestamptz[]) AS p(key, cutoff)
                  WHERE p.key = split_part(t.source, ':', 1) AND t.{stamp} < p.cutoff)
"""


def purge_expired(now: datetime | None = None, url: str | None = None, *,
                  margin_s: int = RETENTION_MARGIN_S) -> dict[str, int]:
    """Delete expired and unstorable rows from offers and watchlist; returns the counts."""
    now = now or datetime.now(timezone.utc)
    storable = [p for p in POLICIES.values() if p.store]
    params = {"keys": [p.key for p in storable],
              "cutoffs": [now - timedelta(seconds=p.max_age_s - margin_s) for p in storable]}
    counts = {}
    with db.job_scope(url=url) as cur:
        for table, stamp in (("offers", "fetched_at"), ("watchlist", "last_checked_at")):
            cur.execute(_PURGE.format(table=table, stamp=stamp), params)
            counts[table] = cur.rowcount
    return counts


def main(argv: list[str] | None = None) -> int:
    """Print the purge counts as one JSON line; exit 1 on a database error."""
    try:
        result = purge_expired()
    except Exception as exc:
        print(f"retention purge failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
