"""Offline billing tests (Part 30).

No live Stripe. Webhook signatures are built with Stripe's own HMAC scheme
(t=<ts>,v1=<sig> over "<ts>.<payload>") against a test secret, and the checkout
builder runs against a mock client. Live use needs the learner's own Stripe test
keys; the verification + gating logic under test is identical.
"""
import json
import time

import pytest
import stripe

from dealfinder.billing import (
    Entitlement,
    QuotaExceeded,
    create_checkout_session,
    handle_webhook,
    meter_usage,
    plan_for,
    within_quota,
)

WEBHOOK_SECRET = "whsec_test_secret"


class _User:
    def __init__(self, uid, email=None):
        self.id = uid
        self.email = email


def _signed(payload: dict, secret=WEBHOOK_SECRET, ts=None):
    """Build a real Stripe-Signature header for `payload` using Stripe's helper."""
    body = json.dumps(payload).encode()
    ts = ts or int(time.time())
    sig = stripe.WebhookSignature._compute_signature(f"{ts}.{body.decode()}", secret)
    return body, f"t={ts},v1={sig}"


# --- webhook signature verification ----------------------------------------

def test_webhook_good_signature_maps_to_entitlement():
    event = {
        "object": "event",
        "type": "checkout.session.completed",
        "data": {"object": {
            "client_reference_id": "user-123",
            "metadata": {"user_id": "user-123", "plan": "pro"},
        }},
    }
    body, sig = _signed(event)
    ent = handle_webhook(body, sig, WEBHOOK_SECRET)
    assert ent == Entitlement(user_id="user-123", plan="pro")


def test_webhook_bad_signature_raises():
    body, _ = _signed({"type": "checkout.session.completed", "data": {"object": {}}})
    with pytest.raises(stripe.error.SignatureVerificationError):
        handle_webhook(body, "t=1,v1=deadbeef", WEBHOOK_SECRET)


def test_webhook_wrong_secret_raises():
    body, sig = _signed({"type": "checkout.session.completed", "data": {"object": {}}},
                        secret="whsec_other")
    with pytest.raises(stripe.error.SignatureVerificationError):
        handle_webhook(body, sig, WEBHOOK_SECRET)


def test_webhook_ignores_other_event_types():
    body, sig = _signed({"object": "event", "type": "invoice.paid", "data": {"object": {}}})
    assert handle_webhook(body, sig, WEBHOOK_SECRET) is None


# --- plan gating / metering -------------------------------------------------

def test_free_plan_hits_quota_and_is_blocked():
    store = {}
    free_limit = plan_for("free").monthly_searches  # 25
    for _ in range(free_limit):
        meter_usage(store, "u1", "free")
    assert store["u1"] == free_limit
    assert not within_quota(store, "u1", "free")
    with pytest.raises(QuotaExceeded):
        meter_usage(store, "u1", "free")


def test_pro_plan_has_higher_quota():
    store = {}
    free_limit = plan_for("free").monthly_searches   # 25
    pro_limit = plan_for("pro").monthly_searches      # 1000
    assert pro_limit > free_limit
    # a usage level that blocks free is still fine for pro
    store["u2"] = free_limit
    assert not within_quota(store, "u2", "free")
    assert within_quota(store, "u2", "pro")
    meter_usage(store, "u2", "pro")  # no raise
    assert store["u2"] == free_limit + 1


# --- checkout builder shape (mock client, no network) ----------------------

def test_checkout_session_builder_shape(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_PRO", "price_test_pro_123")
    captured = {}

    class _MockSessions:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            return {"id": "cs_test_abc", "url": "https://checkout.stripe.com/pay/cs_test_abc"}

    class _MockClient:
        class checkout:
            Session = _MockSessions

    out = create_checkout_session(_User("user-9", "u@x.com"), "pro", client=_MockClient)
    assert out == {"id": "cs_test_abc", "url": "https://checkout.stripe.com/pay/cs_test_abc"}
    # the session was built with the configured price, the user linkage, and mode
    assert captured["mode"] == "subscription"
    assert captured["line_items"] == [{"price": "price_test_pro_123", "quantity": 1}]
    assert captured["client_reference_id"] == "user-9"
    assert captured["customer_email"] == "u@x.com"
    assert captured["metadata"] == {"user_id": "user-9", "plan": "pro"}


def test_checkout_missing_price_raises(monkeypatch):
    monkeypatch.delenv("STRIPE_PRICE_PRO", raising=False)
    with pytest.raises(ValueError):
        create_checkout_session(_User("u"), "pro", client=object())
