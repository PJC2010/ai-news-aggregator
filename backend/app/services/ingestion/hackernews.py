import asyncio
import re
from datetime import UTC, datetime

from app.services.ingestion.parsing import plain_text
from app.services.ingestion.types import Candidate, FetchResult

AI_PATTERN = re.compile(
    r"\b(ai|artificial intelligence|machine learning|deep learning|llms?|gpt[\w.-]*|"
    r"openai|anthropic|claude|gemini|llama|mistral|qwen|deepseek|neural|"
    r"diffusion|transformers?|pytorch|tensorflow|hugging\s?face|"
    r"computer vision|reinforcement learning|fine.tun\w*)\b",
    re.I,
)


async def fetch_hackernews(client, source, limit: int) -> FetchResult:
    response = await client.get(source.url + "/topstories.json")
    ids = response.json()
    if not isinstance(ids, list):
        raise ValueError("HN topstories must be a list")
    semaphore = asyncio.Semaphore(5)

    async def fetch_one(item_id):
        async with semaphore:
            response = await client.get(source.url + f"/item/{int(item_id)}.json")
        item = response.json()
        if not item or item.get("type") != "story" or item.get("deleted") or item.get("dead"):
            return None
        title, body = item.get("title", ""), plain_text(item.get("text", ""))
        if not AI_PATTERN.search(" ".join([title, body, item.get("url", "")])):
            return None
        discussion = f"https://news.ycombinator.com/item?id={item['id']}"
        return Candidate(
            url=item.get("url") or discussion,
            title=title,
            body=body,
            body_kind="discussion",
            author=item.get("by"),
            published_at=datetime.fromtimestamp(item["time"], UTC),
            external_id=str(item["id"]),
            metadata={
                "hn_item_id": item["id"],
                "hn_points": item.get("score", 0),
                "hn_comments": item.get("descendants", 0),
                "discussion_url": discussion,
            },
        )

    results = await asyncio.gather(*(fetch_one(i) for i in ids[:limit]), return_exceptions=True)
    warnings = [
        f"HN item fetch failed: {type(r).__name__}" for r in results if isinstance(r, Exception)
    ]
    return FetchResult([r for r in results if isinstance(r, Candidate)], warnings=warnings)
