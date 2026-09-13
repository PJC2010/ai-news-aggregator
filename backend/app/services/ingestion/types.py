from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Candidate:
    url: str
    title: str
    body: str = ""
    author: str | None = None
    published_at: datetime | None = None
    external_id: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class FetchResult:
    items: list[Candidate]
    state: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
