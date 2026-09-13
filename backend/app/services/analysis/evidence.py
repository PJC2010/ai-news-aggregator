import hashlib
import json
import re
from urllib.parse import urlsplit

from sqlalchemy import select

from app.models import Article, ClusterArticle, Source
from app.services.processing.dedup import canonicalize_url


def digest(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def build_evidence(session, cluster) -> dict:
    rows = session.execute(
        select(Article, Source)
        .join(ClusterArticle, ClusterArticle.article_id == Article.id)
        .join(Source, Source.id == Article.source_id)
        .where(ClusterArticle.cluster_id == cluster.id)
    ).all()
    rows.sort(
        key=lambda row: (
            row.Article.id != cluster.primary_article_id,
            -row.Source.authority_score,
            -min(len((row.Article.body or "").split()), 3000),
            row.Article.canonical_url,
        )
    )
    articles, links, limitations = [], set(), []
    for article, source in rows[:4]:
        words = (article.body or "").split()
        body = " ".join(words[:1200])[:12000]
        articles.append(
            {
                "id": str(article.id),
                "title": article.title,
                "url": article.canonical_url,
                "body": body,
                "published_at": article.published_at.isoformat() if article.published_at else None,
                "source_name": source.name,
                "source_category": source.category,
            }
        )
        if len(body.split()) < 80:
            limitations.append(f"Article {article.id} has limited source text.")
        if len(words) > 1200 or len(" ".join(words[:1200])) > 12000:
            limitations.append(
                f"Article {article.id} is a truncated excerpt; omitted sections may contain "
                "additional evidence. Claims about missing details apply only to this excerpt."
            )
        for raw in [article.canonical_url, *re.findall(r'https?://[^\s<>"\]]+', body)]:
            try:
                url = canonicalize_url(raw.rstrip(".,;:)"))
                parts = urlsplit(url)
                if parts.hostname in {"arxiv.org", "www.arxiv.org", "github.com", "www.github.com"}:
                    if parts.path.strip("/"):
                        links.add(url)
            except ValueError:
                continue
    if len(rows) == 1:
        limitations.append("One distinct article; independent corroboration is unavailable.")
    if len(rows) > 4:
        limitations.append(
            "Only the primary article and three selected supporting articles are included."
        )
    return {
        "cluster_article_count": len(rows),
        "articles": articles,
        "allowed_links": sorted(links),
        "limitations": limitations,
    }


def enough_evidence(evidence) -> bool:
    return sum(len(article["body"].split()) for article in evidence["articles"]) >= 40


def validate_evidence_links(analysis, evidence):
    allowed = set(evidence["allowed_links"])
    for link in analysis.code_paper_links:
        if canonicalize_url(link) not in allowed:
            raise ValueError("Analysis cited a code/paper URL absent from supplied evidence")
