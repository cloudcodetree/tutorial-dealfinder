"""What each store's terms let us do with its rows: one table, asked before every signal.

A row's ``source`` is ``"<Key>"`` or ``"<Key>:<detail>"`` (``"BestBuy:sale"``,
``"eBay:Used"``). The key picks a :class:`SourcePolicy`. An unknown key has no
policy and is denied everything, so a new source stays inert until it is added
here on purpose.

Each rule cites the terms digest in the launch research (§3):

- **eBay** (API License Agreement). §9.5: eBay content may not be used "to suggest
  or model prices", so no verdict and no score. §9.10: it may not "train
  algorithms, conduct machine learning", so no embedding, no training and no eval
  use. §8.1(b): it "may not be co-mingled or combined with non-eBay Content", so it
  is never ranked against or mixed with other stores. §8.1(c): listings may be at
  most 6 hours old, so it is never stored, and any cache is shorter than that.
- **Best Buy** (developer terms, 2021-02-23). Its pricing-analysis ban covers
  analysis done "on behalf of or for the benefit of any third party (such as other
  retailers)", so shopper-facing verdicts are allowed. The data is cached at most
  72 hours. Its attribution and logo appear on every page and screen that uses
  its data. The data is never shared with or used for other retailers.
- **Course-only sources** (RapidAPI, Apify, Amazon, Shopify, Firecrawl, iTunes)
  keep the lessons working but are off at launch (``launch=False``).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourcePolicy:
    key: str
    verdicts: bool
    store: bool
    embed: bool
    comingle: bool
    max_age_s: int
    launch: bool
    attribution: dict | None


_BESTBUY_ATTRIBUTION = {
    "source": "BestBuy",
    "text": "Prices and product data from Best Buy",
    "url": "https://www.bestbuy.com",
    "logo": "bestbuy",
}


def _course(key: str) -> SourcePolicy:
    return SourcePolicy(key, verdicts=True, store=True, embed=True, comingle=True,
                        max_age_s=72 * 3600, launch=False, attribution=None)


POLICIES: dict[str, SourcePolicy] = {
    "BestBuy": SourcePolicy("BestBuy", verdicts=True, store=True, embed=True, comingle=True,
                            max_age_s=72 * 3600, launch=True, attribution=_BESTBUY_ATTRIBUTION),
    "eBay": SourcePolicy("eBay", verdicts=False, store=False, embed=False, comingle=False,
                         max_age_s=6 * 3600, launch=True, attribution=None),
    **{k: _course(k) for k in ("RapidAPI", "Apify", "Amazon", "Shopify", "Firecrawl", "iTunes")},
}

LAUNCH_SOURCES: frozenset[str] = frozenset(k for k, p in POLICIES.items() if p.launch)


def source_key(source: str) -> str:
    """``"eBay:Used"`` -> ``"eBay"``: the text before the first ``:``."""
    return (source or "").split(":", 1)[0]


def policy_for(source: str) -> SourcePolicy | None:
    """The policy for a row's source, or None for a source we have no terms for."""
    return POLICIES.get(source_key(source))


def may_verdict(source: str) -> bool:
    p = policy_for(source)
    return bool(p and p.verdicts)


def may_store(source: str) -> bool:
    p = policy_for(source)
    return bool(p and p.store)


def may_embed(source: str) -> bool:
    p = policy_for(source)
    return bool(p and p.embed)


def may_comingle(source: str) -> bool:
    p = policy_for(source)
    return bool(p and p.comingle)
