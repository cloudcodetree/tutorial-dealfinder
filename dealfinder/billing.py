"""Payments & SaaS mechanics (Part 34) — Stripe Checkout, webhooks, metering.

Real Stripe integration in test-mode shape:

  - `create_checkout_session(user, plan)` builds a Stripe Checkout Session for a
    plan's price and returns the hosted-checkout URL.
  - `handle_webhook(payload, sig_header, secret)` verifies the Stripe signature
    and maps `checkout.session.completed` → an entitlement (which plan a user is
    now on).
  - `PLANS` defines free/pro and their monthly search quota.
  - `meter_usage` / `within_quota` are the usage-metering + plan-gate the API
    calls on every search.

Runs live only with the learner's OWN Stripe test keys (`STRIPE_SECRET_KEY`,
price IDs, and the webhook signing secret from the Stripe dashboard / CLI). The
tests in `tests/test_billing.py` are fully offline: signatures are verified with
Stripe's own HMAC helper against a test secret, and the checkout builder runs
against a mocked Stripe client — no network, no live Stripe.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import stripe


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    monthly_searches: int  # quota; -1 == unlimited
    price_env: str  # env var holding the Stripe Price ID for this plan


# The catalog. Price IDs come from the learner's Stripe dashboard (test mode).
PLANS: dict[str, Plan] = {
    "free": Plan(key="free", name="Free", monthly_searches=25, price_env=""),
    "pro": Plan(key="pro", name="Pro", monthly_searches=1000, price_env="STRIPE_PRICE_PRO"),
}


class QuotaExceeded(Exception):
    """Raised when a user has spent their plan's monthly quota."""


def plan_for(key: str) -> Plan:
    return PLANS.get(key, PLANS["free"])


# --- usage metering + plan gating ------------------------------------------
# `store` is any dict-like {user_id: count}. In production this is a row in
# Postgres/Redis with a monthly reset; the gating logic is identical.

def within_quota(store: dict, user_id: str, plan_key: str) -> bool:
    """True if the user still has search budget left on their plan this period."""
    plan = plan_for(plan_key)
    if plan.monthly_searches < 0:
        return True
    return store.get(user_id, 0) < plan.monthly_searches


def meter_usage(store: dict, user_id: str, plan_key: str, n: int = 1) -> int:
    """Record `n` units of usage, gating on the plan quota first.

    Raises `QuotaExceeded` if this would push the user past their plan limit,
    so the caller can return HTTP 402/429 and prompt an upgrade. Returns the new
    running total on success.
    """
    plan = plan_for(plan_key)
    used = store.get(user_id, 0)
    if plan.monthly_searches >= 0 and used + n > plan.monthly_searches:
        raise QuotaExceeded(
            f"{plan.name} plan allows {plan.monthly_searches} searches/mo (used {used})"
        )
    store[user_id] = used + n
    return store[user_id]


# --- Stripe Checkout --------------------------------------------------------

def create_checkout_session(
    user,
    plan_key: str,
    *,
    success_url: str = "https://dealfinder.app/billing/success",
    cancel_url: str = "https://dealfinder.app/billing/cancel",
    client=stripe,
) -> dict:
    """Create a Stripe Checkout Session for `plan_key` and return {id, url}.

    `user` is the authenticated principal (see auth.py) — we pass its id/email
    to Stripe so the webhook can map the completed payment back to the user.
    `client` is injected so tests can pass a mock instead of the live SDK.
    """
    plan = plan_for(plan_key)
    price_id = os.getenv(plan.price_env) if plan.price_env else None
    if not price_id:
        raise ValueError(f"no Stripe price configured for plan '{plan_key}' ({plan.price_env})")

    session = client.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=user.id,
        customer_email=getattr(user, "email", None),
        metadata={"user_id": user.id, "plan": plan_key},
    )
    return {"id": session["id"], "url": session["url"]}


# --- Webhook ----------------------------------------------------------------

@dataclass(frozen=True)
class Entitlement:
    """What a verified webhook tells us to grant."""

    user_id: str
    plan: str


def handle_webhook(payload: bytes, sig_header: str, secret: str) -> Entitlement | None:
    """Verify a Stripe webhook signature and map it to an entitlement.

    Raises `stripe.error.SignatureVerificationError` if the signature is bad —
    the caller must let that bubble to a 400 so forged events are rejected.
    Returns an `Entitlement` for `checkout.session.completed`, else None (we
    ignore event types we don't act on).
    """
    event = stripe.Webhook.construct_event(payload, sig_header, secret)
    if event["type"] != "checkout.session.completed":
        return None
    # `construct_event` returns Stripe's rich objects (dict subclasses that only
    # allow indexing keys that exist); read defensively with membership checks.
    def _get(obj, key, default=None):
        return obj[key] if key in obj else default

    session = event["data"]["object"]
    meta = _get(session, "metadata", {})
    user_id = _get(session, "client_reference_id") or _get(meta, "user_id")
    if not user_id:
        return None
    return Entitlement(user_id=user_id, plan=_get(meta, "plan", "pro"))
