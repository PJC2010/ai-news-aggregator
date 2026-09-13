"""Strict output contracts; URL grounding is checked separately against evidence."""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    TypeAdapter,
    field_validator,
)

Sentence = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=1200)
]
Audience = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120)
]
Explanation = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=2400)
]
Link = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2048)]
_http_url = TypeAdapter(HttpUrl)


class SummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sentences: Annotated[list[Sentence], Field(min_length=3, max_length=5)]


class AnalysisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    event_type: Literal[
        "model_release",
        "paper",
        "funding",
        "regulation",
        "research_breakthrough",
        "tool_release",
        "other",
    ]
    technical_significance: Annotated[int, Field(strict=True, ge=1, le=10)]
    who_should_care: Annotated[list[Audience], Field(min_length=1, max_length=8)]
    why_it_matters: Explanation
    what_to_watch: Explanation
    code_paper_links: Annotated[list[Link], Field(max_length=12)]
    hype_check: Literal["overhyped", "underhyped", "accurate"]

    @field_validator("code_paper_links")
    @classmethod
    def validate_links(cls, links: list[str]) -> list[str]:
        for link in links:
            if any(character.isspace() for character in link):
                raise ValueError("Links must not contain whitespace")
            parsed = _http_url.validate_python(link)
            if parsed.username or parsed.password:
                raise ValueError("Links must not include credentials")
        # Keep the original spelling for the evidence allowlist comparison.
        return links
