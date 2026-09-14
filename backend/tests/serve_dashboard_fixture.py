"""Browser-test server: real API + ephemeral SQLite + a fake identity service.

Only this test executable mounts the fake Auth route. Never use it to serve real
news. The production application has no test-token or SQLite bypass.
"""

import base64
import json
import time
from uuid import UUID

import uvicorn
from fastapi import Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from test_dashboard import seed_events

from app.config import Settings, get_settings
from app.database import get_session
from app.main import app
from app.models import Base

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


@event.listens_for(engine, "connect")
def foreign_keys(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")


Base.metadata.create_all(engine)
factory = sessionmaker(engine, expire_on_commit=False)
seed_events(factory)


def session_override():
    with factory() as session:
        yield session


app.dependency_overrides[get_session] = session_override
app.dependency_overrides[get_settings] = lambda: Settings(
    _env_file=None,
    supabase_url="http://127.0.0.1:3200",
    supabase_publishable_key="test-publishable",
)


@app.post("/auth/v1/logout")
def fake_logout():
    return {}


@app.get("/auth/v1/user")
def fake_auth(authorization: str | None = Header(None)):
    # The browser tests use fixed fixture identities. This is intentionally NOT
    # JWT verification; it substitutes for the remote Supabase test service only.
    try:
        token = (authorization or "").removeprefix("Bearer ")
        header, payload, signature = token.split(".")
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if signature != "fixture" or claims["sub"] not in (str(UUID(int=1)), str(UUID(int=2))):
            raise ValueError()
        if claims["exp"] <= time.time():
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, "Invalid test session") from None
    return {
        "id": claims["sub"],
        "email": "alice@example.com" if claims["sub"] == str(UUID(int=1)) else "bob@example.com",
        "role": "authenticated",
        "aud": "authenticated",
        "email_confirmed_at": "2026-09-14T00:00:00Z",
        "is_anonymous": False,
        "app_metadata": {"provider": "email"},
        "user_metadata": {},
        "created_at": "2026-09-14T00:00:00Z",
        "identities": [],
    }


@app.middleware("http")
async def simulated_outage(request, call_next):
    if request.url.path == "/feed" and request.query_params.get("q") == "fixture-offline":
        return JSONResponse({"detail": "simulated outage"}, status_code=503)
    return await call_next(request)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=3200, log_level="warning")
