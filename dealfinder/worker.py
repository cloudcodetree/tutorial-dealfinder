"""Saved searches & the periodic-suggestions worker (Part 29).

A user saves a search ("noise cancelling headphones"). A background job runs that
search on a schedule, and whenever a *new* good deal shows up for it, it notifies
the user — the "we found you a deal" email every price-tracker sends. This module
is the deterministic, offline core of that job:

    run_suggestions(saved, state) -> (notifications, new_state)

- **saved**: the user's saved queries (:class:`SavedSearch`).
- **state**: what the user was last shown, per query (:class:`SuggestionState`)
  — the set of item ids already notified.
- It searches the frozen snapshot with the same ``search_catalog`` pipeline the
  rest of the course uses (Part 5 retrieval + Part 3 two-signal deal score),
  keeps only items that clear a deal-score threshold, **diffs against last-seen**,
  and emits one notification per genuinely new deal. The returned ``new_state`` is
  fed back on the next run so nothing is re-notified (idempotent).

**No network, no email.** Delivery is behind a :class:`Notifier` protocol; the
default :class:`ConsoleNotifier` prints and records dict payloads. Swap in a real
email/push notifier in production without touching the diff logic.

Worked example (the hero cast, spec §3): a saved "noise cancelling headphones"
search surfaces the **Anker Soundcore Q20i at $44.99** (deal score +0.724, top of
the reranked list) as its new-deal notification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .recommend import load_catalog_embeddings
from .schema import Product
from .snapshot import load_products, load_snapshot

# An item must clear this blended two-signal deal score to be worth notifying.
# (The score is median-signal demoted for model-flagged traps — see search.py.)
DEAL_SCORE_THRESHOLD = 0.30


@dataclass(frozen=True)
class SavedSearch:
    """A user's saved query + how many top results to consider each run."""

    user_id: str
    query: str
    k: int = 5


@dataclass
class SuggestionState:
    """Per-query memory of which item ids the user has already been notified about.

    Keyed by ``(user_id, query)``. This is the "last-seen" cursor the diff runs
    against; persist it (DB/KV) between runs in production.
    """

    seen: dict[tuple[str, str], set[str]] = field(default_factory=dict)

    def key(self, s: SavedSearch) -> tuple[str, str]:
        return (s.user_id, s.query)

    def already_seen(self, s: SavedSearch) -> set[str]:
        return self.seen.get(self.key(s), set())

    def mark_seen(self, s: SavedSearch, ids: set[str]) -> None:
        self.seen.setdefault(self.key(s), set()).update(ids)

    def copy(self) -> "SuggestionState":
        return SuggestionState(seen={k: set(v) for k, v in self.seen.items()})


@dataclass
class Notification:
    """One "new deal" payload for one item (delivery-agnostic)."""

    user_id: str
    query: str
    item_id: str
    title: str
    price: float
    deal_score: float

    def as_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "query": self.query,
            "item_id": self.item_id,
            "title": self.title,
            "price": self.price,
            "deal_score": round(self.deal_score, 4),
        }


@runtime_checkable
class Notifier(Protocol):
    """Delivery seam. Real notifiers (email/push) implement this; tests use the
    console stub. No network here."""

    def notify(self, notification: Notification) -> None: ...


class ConsoleNotifier:
    """Default notifier: prints each payload and records it (for tests/inspection)."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def notify(self, notification: Notification) -> None:
        payload = notification.as_dict()
        self.sent.append(payload)
        print(
            f"[deal] {payload['user_id']} · {payload['query']!r} → "
            f"{payload['title'][:48]} ${payload['price']} "
            f"(score {payload['deal_score']})"
        )


# ---------------------------------------------------------------------------
# The catalog seam — deterministic search over the frozen snapshot.
# ---------------------------------------------------------------------------
@dataclass
class Catalog:
    """The corpus the worker searches: products, cached embeddings, medians.

    Bundled so a run is pure w.r.t. its inputs (a test can hand in a shrunk or
    perturbed catalog to simulate a *newly appearing* deal without touching disk).
    """

    products: list[Product]
    embeddings: object  # np.ndarray aligned to products
    medians: dict[str, float]


def load_catalog(path: str | None = None) -> Catalog:
    """Build a :class:`Catalog` from the committed snapshot (offline)."""
    items = load_snapshot(path)
    products, emb = load_catalog_embeddings(load_products(path))
    medians = {r["id"]: float(r["median_price_at_capture"]) for r in items}
    return Catalog(products=products, embeddings=emb, medians=medians)


def find_deals(catalog: Catalog, query: str, k: int) -> list[tuple[Product, float]]:
    """Top-k search results for ``query`` that clear the deal-score threshold.

    Uses the course's ``search_catalog`` (semantic + BM25 → RRF → two-signal value
    rerank), then keeps only items whose blended deal score is a real deal.
    """
    from .search import search_catalog

    results = search_catalog(
        query, catalog.products, catalog.embeddings, catalog.medians, k=k
    )
    return [(p, score) for _, p, score in results if score >= DEAL_SCORE_THRESHOLD]


# ---------------------------------------------------------------------------
# The job.
# ---------------------------------------------------------------------------
def run_suggestions(
    saved: list[SavedSearch],
    state: SuggestionState,
    *,
    catalog: Catalog | None = None,
    notifier: Notifier | None = None,
) -> tuple[list[Notification], SuggestionState]:
    """Run every saved search, diff against last-seen, notify only NEW deals.

    Returns ``(notifications, new_state)``. ``new_state`` is a fresh copy with the
    newly-notified ids folded in, so passing it back on the next run emits nothing
    (idempotent). Deterministic: same inputs → same notifications.
    """
    catalog = catalog if catalog is not None else load_catalog()
    notifier = notifier if notifier is not None else ConsoleNotifier()
    new_state = state.copy()

    notifications: list[Notification] = []
    for s in saved:
        seen = new_state.already_seen(s)
        deals = find_deals(catalog, s.query, s.k)
        fresh_ids: set[str] = set()
        for product, score in deals:
            if product.id in seen:
                continue  # already told the user about this one
            note = Notification(
                user_id=s.user_id,
                query=s.query,
                item_id=product.id,
                title=product.title,
                price=product.price,
                deal_score=score,
            )
            notifier.notify(note)
            notifications.append(note)
            fresh_ids.add(product.id)
        if fresh_ids:
            new_state.mark_seen(s, fresh_ids)

    return notifications, new_state
