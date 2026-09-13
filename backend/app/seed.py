import json
from importlib.resources import files

from sqlalchemy import select

from app.models import Source


def seed_sources(session):
    count = 0
    for source in json.loads(files("app").joinpath("sources.json").read_text()):
        if not session.scalar(select(Source).where(Source.url == source["url"])):
            session.add(Source(**source))
            count += 1
    session.commit()
    return count
