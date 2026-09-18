from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import Identity, require_user
from app.database import get_session
from app.models import User


class Feature(StrEnum):
    UNLIMITED_TOPICS = "unlimited_topics"
    FULL_ANALYSIS = "full_analysis"
    ARCHIVE = "archive"
    ALERTS = "alerts"
    API_QUOTAS = "api_quotas"


PRO_FEATURES = frozenset(Feature)


@dataclass(frozen=True)
class Entitlements:
    user: User
    tier: str
    features: frozenset[Feature]

    def has(self, feature: Feature) -> bool:
        return feature in self.features

    def require(self, feature: Feature) -> None:
        if not self.has(feature):
            raise HTTPException(403, f"A pro subscription is required for {feature.value}")


def entitlements_for(user: User, now: datetime | None = None) -> Entitlements:
    """Interpret persisted state only; callers and Supabase metadata cannot grant access."""
    now = now or datetime.now(UTC)
    expires = user.entitlement_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    paid = user.subscription_tier == "pro" and (expires is None or expires > now)
    return Entitlements(user, "pro" if paid else "free", PRO_FEATURES if paid else frozenset())


def current_entitlements(
    identity: Identity = Depends(require_user), session: Session = Depends(get_session)
) -> Entitlements:
    from app.preferences import ensure_profile

    return entitlements_for(ensure_profile(session, identity))
