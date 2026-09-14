"""Validate each customer token with Supabase; never trust client-supplied identity.

The Auth user endpoint supports both current asymmetric and legacy signed tokens,
and checks the user's current record. No service-role key or shared JWT secret is
needed. This deliberately favors revocation/account checks over local JWT caching.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import Depends, Header, HTTPException

from app.config import Settings, get_settings


@dataclass(frozen=True)
class Identity:
    id: UUID
    email: str


def verify_user(token: str, settings: Settings) -> Identity:
    base = settings.supabase_url.rstrip("/")
    try:
        parsed = urlsplit(base)
    except ValueError as exc:
        raise HTTPException(503, "Customer sign-in is not configured") from exc
    if (
        not settings.supabase_publishable_key
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or (
            parsed.scheme != "https"
            and not (
                settings.app_env == "development"
                and parsed.scheme == "http"
                and parsed.hostname in ("localhost", "127.0.0.1", "::1")
            )
        )
    ):
        raise HTTPException(503, "Customer sign-in is not configured")
    try:
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            response = client.get(
                f"{base}/auth/v1/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": settings.supabase_publishable_key,
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Sign-in service is temporarily unavailable") from exc
    if response.status_code in (401, 403):
        raise HTTPException(401, "Session expired; sign in again")
    if response.status_code != 200:
        raise HTTPException(503, "Sign-in service is temporarily unavailable")
    try:
        user = response.json()
        identity = Identity(id=UUID(user["id"]), email=user["email"])
        if (
            user.get("role") != "authenticated"
            or user.get("is_anonymous", False)
            or not user.get("email_confirmed_at")
            or not isinstance(identity.email, str)
            or not 1 <= len(identity.email) <= 320
        ):
            raise ValueError("A confirmed email account is required")
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(401, "A confirmed email account is required") from exc
    return identity


def require_user(
    authorization: str | None = Header(None), settings: Settings = Depends(get_settings)
) -> Identity:
    if not authorization:
        raise HTTPException(401, "Sign in to continue", headers={"WWW-Authenticate": "Bearer"})
    scheme, _, token = authorization.partition(" ")
    if (
        scheme.lower() != "bearer"
        or not token
        or len(token) > 16384
        or any(character.isspace() for character in token)
    ):
        raise HTTPException(401, "Invalid session")
    return verify_user(token, settings)
