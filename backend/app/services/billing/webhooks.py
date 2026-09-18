import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import StripeEvent, User


def verify_event(payload: bytes, signature: str | None, settings: Settings) -> dict:
    secrets = [
        value.strip() for value in settings.stripe_webhook_secrets.split(",") if value.strip()
    ]
    if not signature or not secrets:
        raise HTTPException(400, "Invalid Stripe signature")
    fields: dict[str, list[str]] = {}
    for part in signature.split(","):
        key, separator, value = part.partition("=")
        if separator:
            fields.setdefault(key, []).append(value)
    try:
        timestamp = int(fields["t"][0])
    except (KeyError, ValueError):
        raise HTTPException(400, "Invalid Stripe signature") from None
    if abs(int(time.time()) - timestamp) > 300:
        raise HTTPException(400, "Invalid Stripe signature")
    signed = str(timestamp).encode() + b"." + payload
    valid = any(
        hmac.compare_digest(
            candidate, hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        )
        for secret in secrets
        for candidate in fields.get("v1", [])
    )
    if not valid:
        raise HTTPException(400, "Invalid Stripe signature")
    try:
        event = json.loads(payload)
        if not isinstance(event["id"], str) or not isinstance(event["created"], int):
            raise ValueError
        return event
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise HTTPException(400, "Invalid Stripe event") from None


def _timestamp(value) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if isinstance(value, (int, float)) else None


def _utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def process_event(session: Session, event: dict, settings: Settings) -> bool:
    """Store every receipt, but only let newer subscription snapshots change access."""
    created = datetime.fromtimestamp(event["created"], UTC)
    receipt = StripeEvent(
        id=event["id"], event_type=event.get("type", "unknown"), created_at=created
    )
    session.add(receipt)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return False

    kind = event.get("type", "")
    obj = event.get("data", {}).get("object", {})
    if kind.startswith("customer.subscription."):
        customer_id = obj.get("customer")
        user = None
        if isinstance(customer_id, str) and customer_id:
            user = (
                session.query(User)
                .filter(User.stripe_customer_id == customer_id)
                .with_for_update()
                .one_or_none()
            )
        previous = _utc(user.stripe_state_created_at) if user else None
        if user and (previous is None or created > previous):
            status = obj.get("status")
            period_end = _timestamp(obj.get("current_period_end"))
            user.stripe_subscription_id = obj.get("id")
            user.stripe_subscription_status = status
            items = obj.get("items", {}).get("data", [])
            user.stripe_price_id = items[0].get("price", {}).get("id") if items else None
            user.stripe_state_created_at = created
            if status in ("active", "trialing") and period_end:
                user.subscription_tier = "pro"
                user.entitlement_expires_at = period_end
            elif status == "past_due":
                # Failed renewals retain access for a bounded operational grace period.
                user.entitlement_expires_at = (period_end or created) + timedelta(
                    days=settings.stripe_past_due_grace_days
                )
                user.subscription_tier = "pro"
            elif status == "canceled" and period_end and period_end > datetime.now(UTC):
                # Cancellation-at-period-end remains pro only through the paid-through time.
                user.subscription_tier = "pro"
                user.entitlement_expires_at = period_end
            else:
                user.subscription_tier = "free"
                user.entitlement_expires_at = None
    session.commit()
    return True
