import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.auth import Identity, require_user
from app.config import get_settings
from app.database import get_session
from app.main import app
from app.models import StripeEvent, User
from app.services.billing.entitlements import Feature, entitlements_for
from app.services.billing.stripe import StripeClient
from app.services.billing.webhooks import process_event

ALICE = Identity(UUID(int=1), "alice@example.com")


@pytest.fixture
def billing_client(factory, settings):
    settings.stripe_webhook_secrets = "old-secret,new-secret"
    settings.stripe_pro_price_id = "price_server_owned"

    def sessions():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[require_user] = lambda: ALICE
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def signed(body: bytes, secret="new-secret", timestamp=None):
    timestamp = timestamp or int(time.time())
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def event(event_id, created, status, period_end, customer="cus_alice"):
    return {
        "id": event_id,
        "created": created,
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_alice",
                "customer": customer,
                "status": status,
                "current_period_end": period_end,
                "items": {"data": [{"price": {"id": "price_server_owned"}}]},
            }
        },
    }


def test_forged_and_stale_webhook_signatures_are_rejected(billing_client):
    body = json.dumps(event("evt_1", int(time.time()), "active", int(time.time()) + 60)).encode()
    assert (
        billing_client.post(
            "/billing/webhook", content=body, headers={"stripe-signature": signed(body, "forged")}
        ).status_code
        == 400
    )
    assert (
        billing_client.post(
            "/billing/webhook",
            content=body,
            headers={"stripe-signature": signed(body, timestamp=int(time.time()) - 301)},
        ).status_code
        == 400
    )


def test_duplicate_and_out_of_order_events_do_not_overwrite_new_state(factory, settings):
    now = int(time.time())
    with factory() as session:
        session.add(User(id=ALICE.id, email=ALICE.email, stripe_customer_id="cus_alice"))
        session.commit()
        assert process_event(session, event("evt_new", now, "active", now + 3600), settings)
        assert not process_event(session, event("evt_new", now, "active", now + 3600), settings)
        assert process_event(session, event("evt_old", now - 10, "canceled", now - 1), settings)
        user = session.get(User, ALICE.id)
        assert user.subscription_tier == "pro"
        assert user.stripe_subscription_status == "active"
        assert session.query(StripeEvent).count() == 2


def test_checkout_and_portal_use_database_customer_ownership(billing_client, factory, monkeypatch):
    calls = []

    def create_customer(self, user):
        calls.append(("customer", user.id))
        return {"id": "cus_alice"}

    def create_checkout(self, user):
        calls.append(("checkout", user.stripe_customer_id, self.settings.stripe_pro_price_id))
        return {"url": "https://checkout.stripe.test/alice"}

    def create_portal(self, user):
        calls.append(("portal", user.stripe_customer_id))
        return {"url": "https://billing.stripe.test/alice"}

    monkeypatch.setattr(StripeClient, "create_customer", create_customer)
    monkeypatch.setattr(StripeClient, "create_checkout", create_checkout)
    monkeypatch.setattr(StripeClient, "create_portal", create_portal)
    response = billing_client.post(
        "/billing/checkout", json={"tier": "pro", "customer": "cus_attacker"}
    )
    assert response.json()["url"].endswith("/alice")
    assert billing_client.post("/billing/portal").status_code == 200
    assert calls[-2:] == [
        ("checkout", "cus_alice", "price_server_owned"),
        ("portal", "cus_alice"),
    ]
    with factory() as session:
        assert session.get(User, ALICE.id).stripe_customer_id == "cus_alice"


@pytest.mark.parametrize(
    "status,period_delta,expected_tier",
    [("canceled", 3600, "pro"), ("canceled", -1, "free"), ("unpaid", 3600, "free")],
)
def test_cancellation_and_downgrade(factory, settings, status, period_delta, expected_tier):
    now = int(time.time())
    with factory() as session:
        session.add(User(id=ALICE.id, email=ALICE.email, stripe_customer_id="cus_alice"))
        session.commit()
        process_event(session, event("evt_status", now, status, now + period_delta), settings)
        assert entitlements_for(session.get(User, ALICE.id)).tier == expected_tier


def test_failed_renewal_has_bounded_grace_then_common_policy_downgrades(factory, settings):
    now = int(time.time())
    settings.stripe_past_due_grace_days = 3
    with factory() as session:
        session.add(User(id=ALICE.id, email=ALICE.email, stripe_customer_id="cus_alice"))
        session.commit()
        process_event(session, event("evt_failed", now, "past_due", now - 1), settings)
        user = session.get(User, ALICE.id)
        assert entitlements_for(user).has(Feature.ALERTS)
        future = datetime.now(UTC) + timedelta(days=4)
        assert entitlements_for(user, future).tier == "free"
