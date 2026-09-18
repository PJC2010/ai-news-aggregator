"""Delivery-time topic filtering; preferences never trigger shared analysis."""

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Identity
from app.models import Article, Cluster, User, UserTopic
from app.services.billing.entitlements import Feature, entitlements_for

TOPICS = {
    "llm": ("Language models", ("language model", "llm", "fine-tun", "inference")),
    "agents": ("AI agents", ("agent", "tool use", "tool-use")),
    "vision": ("Computer vision", ("vision", "image", "video", "multimodal")),
    "open_source": ("Open source", ("open source", "open-source", "open weight", "open-weight")),
    "research": ("Research", ("research", "paper", "benchmark", "arxiv")),
    "policy": ("AI policy", ("policy", "regulat", "governance", "safety")),
    "robotics": ("Robotics", ("robot", "embodied", "autonomous")),
    "infrastructure": ("Infrastructure", ("infrastructure", "gpu", "serving", "deployment")),
}


class TopicsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    topics: list[str] = Field(max_length=len(TOPICS))

    @field_validator("topics")
    @classmethod
    def valid_topics(cls, topics):
        if len(set(topics)) != len(topics) or any(topic not in TOPICS for topic in topics):
            raise ValueError("Choose unique topics from the topic catalog")
        return topics


def ensure_profile(session: Session, identity: Identity) -> User:
    user = session.get(User, identity.id)
    if user is None:
        user = User(id=identity.id, email=identity.email, subscription_tier="free")
        session.add(user)
        try:
            session.commit()
        except IntegrityError:
            # Concurrent first requests can both see a missing profile.
            session.rollback()
            user = session.get(User, identity.id)
            if user is None:
                raise
    if user.email != identity.email:
        user.email = identity.email
        session.commit()
    return user


def profile_payload(session: Session, user: User):
    access = entitlements_for(user)
    return {
        "id": user.id,
        "email": user.email,
        "subscription_tier": access.tier,
        "topic_limit": len(TOPICS) if access.has(Feature.UNLIMITED_TOPICS) else 3,
        "topics": list(
            session.scalars(
                select(UserTopic.topic)
                .where(UserTopic.user_id == user.id)
                .order_by(UserTopic.topic)
            )
        ),
        "available_topics": [{"id": key, "label": value[0]} for key, value in TOPICS.items()],
    }


def save_topics(session: Session, identity: Identity, update: TopicsUpdate):
    ensure_profile(session, identity)
    # Serialize replacements for one user, so concurrent saves cannot combine
    # two valid selections into an invalid free-tier selection.
    user = session.scalar(select(User).where(User.id == identity.id).with_for_update())
    if not entitlements_for(user).has(Feature.UNLIMITED_TOPICS) and len(update.topics) > 3:
        raise HTTPException(422, "Free accounts can follow up to 3 topics")
    session.execute(delete(UserTopic).where(UserTopic.user_id == user.id))
    session.add_all(UserTopic(user_id=user.id, topic=topic) for topic in update.topics)
    session.commit()
    return profile_payload(session, user)


def topic_match(topic: str):
    terms = TOPICS[topic][1]
    return or_(
        *(
            column.icontains(term, autoescape=True)
            for term in terms
            for column in (Cluster.topic, Cluster.summary, Article.title)
        )
    )
