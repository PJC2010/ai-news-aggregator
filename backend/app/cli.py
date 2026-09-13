import argparse
import asyncio
import json
import sys
from importlib.resources import files
from types import SimpleNamespace

from app.config import get_settings
from app.database import session_factory
from app.seed import seed_sources


async def check_sources():
    from app.services.ingestion.http import FetchClient
    from app.services.pipeline import fetch_source

    settings = get_settings().model_copy(update={"source_limit": 2})
    results = []
    async with FetchClient(settings) as client:
        for config in json.loads(files("app").joinpath("sources.json").read_text()):
            try:
                response = await fetch_source(client, SimpleNamespace(**config), settings)
                results.append(
                    {
                        "source": config["name"],
                        "status": "ok",
                        "items": len(response.items),
                        "warnings": response.warnings,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "source": config["name"],
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                    }
                )
    return results


def main():
    parser = argparse.ArgumentParser(description="AI news pipeline operator commands")
    parser.add_argument("command", choices=["seed", "ingest", "check-sources", "warm-model"])
    args = parser.parse_args()
    if args.command == "seed":
        with session_factory()() as session:
            result = {"created": seed_sources(session)}
    elif args.command == "ingest":
        from app.workers.tasks import ingest_once

        result = ingest_once()
    elif args.command == "warm-model":
        from app.services.processing.embeddings import LocalEmbedder

        vector = LocalEmbedder().encode(["AI news intelligence"])[0]
        result = {"model": LocalEmbedder.model_name, "dimensions": len(vector)}
    else:
        result = asyncio.run(check_sources())
    print(json.dumps(result, indent=2, default=str))
    if isinstance(result, dict) and result.get("status") == "partial":
        sys.exit(1)
    if isinstance(result, list) and any(row["status"] != "ok" for row in result):
        sys.exit(1)


if __name__ == "__main__":
    main()
