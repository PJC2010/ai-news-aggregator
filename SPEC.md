# AI News Aggregator — Technical Specification
## For GPT Astra Implementation

**Version:** 1.0  
**Date:** 2026-09-13  
**Author:** Osiel (for Pedro Castle)  
**Target:** Multi-tenant AI/ML news intelligence platform

---

## 1. Product Overview

**One-line pitch:** "Here's what actually mattered in AI today, why it matters, and what to read/run/watch next."

**Target user:** ML engineers, AI researchers, technical founders who need signal, not noise.

**Core differentiator:** Event clustering + technical depth + actionable analysis. Not another link-list.

---

## 2. Architecture Principles

1. **Cluster-level caching** — Analyze once, deliver to many. This is the difference between $0.01/user/day and $0.50/user/day.
2. **RSS/API first, scraping fallback** — Minimize ops burden from HTML changes.
3. **Two-pass LLM** — Cheap model for summary, expensive model for analysis.
4. **Single Postgres** — One database for relational + vector (pgvector).
5. **Python** — NLP ecosystem superiority (sklearn, HDBSCAN, sentence-transformers).

---

## 3. Data Pipeline

```
Sources → Fetch → Parse → Dedup → Cluster → Rank → Summarize → Analyze → Store → Deliver
```

### 3.1 Ingestion Sources (Priority Order)

| Priority | Source | Method | Notes |
|----------|--------|--------|-------|
| P0 | ArXiv (cs.AI, cs.LG, cs.CL, cs.CV) | ArXiv API | Free, no key, bulk fetch |
| P0 | Hacker News | Firebase API | Free, no key, real-time |
| P0 | Company blogs (OpenAI, Anthropic, DeepMind, Meta AI, Google Research, Mistral, Cohere) | RSS | Primary sources, not blogs-about-blogs |
| P1 | GitHub Trending | GitHub API | Underrated source for "what people build" |
| P1 | Reddit (r/MachineLearning, r/LocalLLaMA) | Reddit API | OAuth required, rate-limited |
| P1 | Newsletters (Import AI, The Batch, Interconnects) | RSS where available | |
| P2 | Tech press (The Verge, TechCrunch, Ars) | RSS | Secondary, lower signal |
| Skip | Twitter/X | — | API too expensive for MVP |

### 3.2 Deduplication

Two-stage:
1. **Fast path:** URL hash + canonical URL normalization (catches exact reposts)
2. **Content path:** SimHash on article body (catches near-duplicates, syndicated content)

### 3.3 Event Clustering

When OpenAI drops a model, 40 blogs cover it. Users want ONE summary.

**Method:**
1. Embed article title + first 300 words
   - Use OpenAI `text-embedding-3-small` OR local `all-MiniLM-L6-v2` (free, runs on CPU)
2. Cluster using HDBSCAN (density-based, handles variable cluster sizes)
   - Alternative: Simple cosine similarity threshold (0.85) for MVP
3. Pick "best" article per cluster:
   - Highest source authority score + most complete content
4. Summarize the cluster, not individual articles

### 3.4 Ranking/Scoring

Score clusters by:
- **Source diversity** — 10 different source types > 10 blogs
- **Engagement signals** — HN points, Reddit upvotes, GitHub stars
- **Recency decay** — 2 hours ago > 2 days ago
- **User topic match** — User subscribed to "LLM fine-tuning" boosts relevant clusters

---

## 4. LLM Pipeline

### Pass 1 — Summary (Cheap Model)

**Input:** Best article from cluster + 2-3 supporting articles for context  
**Output:** 3-5 sentence technical summary  
**Model:** GPT-4o-mini, DeepSeek, or Claude Haiku  
**Purpose:** Extraction, not analysis. Good enough.

### Pass 2 — Analysis (Better Model, Structured Output)

**Input:** Summary + article metadata + related papers/repos  
**Output:** Structured JSON:

```json
{
  "event_type": "model_release|paper|funding|regulation|research_breakthrough|tool_release",
  "technical_significance": 1-10,
  "who_should_care": ["LLM engineers", "CV researchers", "MLOps"],
  "why_it_matters": "2-3 sentences of actual analysis",
  "what_to_watch": "Next steps, implications, or related work to monitor",
  "code_paper_links": ["arxiv.org/abs/...", "github.com/..."],
  "hype_check": "overhyped|underhyped|accurate"
}
```

**Model:** GPT-4o, Claude Sonnet, or DeepSeek V4  
**Purpose:** This IS the product. Don't cheap out here.

### Cost Control (Critical)

- Cache aggressively at cluster level
- Per-user personalization happens at DELIVERY layer (filtering/ranking), not ANALYSIS layer
- Target: $0.01-0.03 per user per day in LLM costs

---

## 5. Database Schema (PostgreSQL + pgvector)

```sql
-- Sources we monitor
CREATE TABLE sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    url VARCHAR(512) NOT NULL UNIQUE,
    type VARCHAR(50) NOT NULL, -- 'rss', 'api', 'scraped'
    authority_score INTEGER DEFAULT 5, -- 1-10
    last_fetched_at TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Raw articles
CREATE TABLE articles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES sources(id),
    url VARCHAR(512) NOT NULL UNIQUE,
    canonical_url VARCHAR(512),
    title VARCHAR(512) NOT NULL,
    body TEXT,
    author VARCHAR(255),
    published_at TIMESTAMP,
    fetched_at TIMESTAMP DEFAULT NOW(),
    content_hash VARCHAR(64), -- SimHash
    embedding VECTOR(1536), -- OpenAI text-embedding-3-small
    metadata JSONB, -- HN points, Reddit score, etc.
    created_at TIMESTAMP DEFAULT NOW()
);

-- Event clusters
CREATE TABLE clusters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic VARCHAR(255), -- auto-generated or manual
    summary TEXT, -- Pass 1 output
    analysis JSONB, -- Pass 2 output
    significance_score INTEGER, -- 1-10 from analysis
    event_type VARCHAR(50),
    primary_article_id UUID REFERENCES articles(id),
    cluster_size INTEGER DEFAULT 1, -- how many articles grouped
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Join table
CREATE TABLE cluster_articles (
    cluster_id UUID REFERENCES clusters(id),
    article_id UUID REFERENCES articles(id),
    is_primary BOOLEAN DEFAULT false,
    similarity_score FLOAT,
    PRIMARY KEY (cluster_id, article_id)
);

-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255), -- if not using Clerk/Supabase
    subscription_tier VARCHAR(50) DEFAULT 'free', -- 'free', 'pro', 'team'
    stripe_customer_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);

-- User topic preferences
CREATE TABLE user_topics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    topic VARCHAR(100) NOT NULL, -- 'llm', 'cv', 'rl', 'ai_policy', etc.
    weight INTEGER DEFAULT 5, -- 1-10, how much they care
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, topic)
);

-- Generated digests
CREATE TABLE digests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    date DATE NOT NULL,
    clusters_included UUID[], -- array of cluster IDs
    delivery_status VARCHAR(50) DEFAULT 'pending', -- 'pending', 'sent', 'failed'
    sent_at TIMESTAMP,
    opened_at TIMESTAMP, -- email tracking
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, date)
);

-- API keys for developer access
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    key_hash VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_articles_embedding ON articles USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_articles_published ON articles(published_at);
CREATE INDEX idx_articles_source ON articles(source_id);
CREATE INDEX idx_clusters_score ON clusters(significance_score DESC);
CREATE INDEX idx_clusters_created ON clusters(created_at);
CREATE INDEX idx_digests_user_date ON digests(user_id, date);
```

---

## 6. Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.11+ | NLP ecosystem |
| API Framework | FastAPI | Async, auto-docs, modern |
| Task Queue | Celery + Redis | Battle-tested, Python-native |
| Database | PostgreSQL 15+ + pgvector | One DB for relational + vector |
| Embeddings | OpenAI text-embedding-3-small OR sentence-transformers/all-MiniLM-L6-v2 | Cost vs. quality tradeoff |
| Clustering | HDBSCAN (hdbscan library) | Density-based, variable cluster sizes |
| Frontend | Next.js 14+ (React) | SSR, good DX |
| Email | Resend or Postmark | Developer-friendly, good deliverability |
| Auth | Clerk or Supabase Auth | Don't build auth |
| Billing | Stripe | Standard |
| Hosting | Railway or Fly.io | Simple, scales, no k8s |

---

## 7. API Endpoints (FastAPI)

```
# Public
GET  /health                          # Health check
POST /auth/signup                     # Create account
POST /auth/login                      # Get JWT

# Authenticated
GET  /me                              # Current user profile
PUT  /me/topics                       # Update topic preferences
GET  /me/digests                      # List past digests
GET  /me/digests/{date}               # Get specific digest

GET  /clusters                        # List clusters (paginated, filterable)
GET  /clusters/{id}                   # Full cluster detail with analysis
GET  /clusters/today                  # Today's top clusters

# Developer API (API key auth)
GET  /api/v1/clusters                 # JSON API for developers
GET  /api/v1/clusters/{id}
GET  /api/v1/analysis/{id}            # Just the structured analysis

# Webhooks
POST /webhooks/stripe                 # Billing events
```

---

## 8. MVP Build Order

### Week 1-2: Pipeline Core
- [ ] ArXiv ingestion (cs.AI, cs.LG, cs.CL, cs.CV)
- [ ] HN ingestion (Firebase API)
- [ ] RSS ingestion for 10 company blogs
- [ ] Article parsing (trafilatura or readability-lxml)
- [ ] URL dedup + SimHash near-dup detection
- [ ] Basic clustering (cosine similarity threshold)
- [ ] PostgreSQL schema setup

### Week 3: Analysis Layer
- [ ] Embedding generation (OpenAI or local)
- [ ] HDBSCAN clustering (upgrade from threshold)
- [ ] Pass 1: Summary generation
- [ ] Pass 2: Structured analysis generation
- [ ] Cluster ranking/scoring algorithm

### Week 4: Delivery
- [ ] Email digest generation (daily, 8am user-local)
- [ ] Resend/Postmark integration
- [ ] Basic web dashboard (Next.js)
  - [ ] Cluster list view
  - [ ] Cluster detail view
  - [ ] User settings/topics
- [ ] Stripe integration
  - [ ] Free tier: daily digest, 3 topics
  - [ ] Pro tier ($12/mo): unlimited topics, API access, real-time alerts

### Post-MVP (Do NOT build yet)
- Reddit ingestion
- GitHub trending
- API access for developers
- Telegram/Slack bots
- Custom topic learning from clicks
- Team plans

---

## 9. Cost Model

Assuming 100 free + 50 paid users at month 3:

| Item | Monthly Cost |
|------|--------------|
| LLM API (50 clusters/day × 2 passes) | $30-80 |
| Embedding API | $5-10 |
| Postgres + Redis (Railway/Supabase) | $20-40 |
| Email sending | $10-20 |
| Hosting/misc | $10-20 |
| **Total** | **~$75-170/mo** |

Revenue at $12/mo × 50 users = $600/mo. Healthy margin.

**Critical:** Cluster-level caching keeps LLM costs flat as users grow.

---

## 10. Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Redis
REDIS_URL=redis://host:6379/0

# LLM
OPENAI_API_KEY=sk-...
# OR
ANTHROPIC_API_KEY=sk-ant-...
# OR
DEEPSEEK_API_KEY=...

# Email
RESEND_API_KEY=re_...
# OR
POSTMARK_API_KEY=...

# Auth
CLERK_SECRET_KEY=sk_...
CLERK_PUBLISHABLE_KEY=pk_...
# OR
SUPABASE_URL=https://...
SUPABASE_ANON_KEY=eyJ...

# Billing
STRIPE_SECRET_KEY=sk_...
STRIPE_WEBHOOK_SECRET=whsec_...

# App
APP_ENV=development
APP_URL=http://localhost:3000
```

---

## 11. Success Metrics

- **Activation:** User opens first digest within 24h of signup
- **Retention:** 4+ digests opened in first week
- **Engagement:** Click-through rate on cluster links >20%
- **Conversion:** Free → Pro >5%
- **Cost:** LLM spend per user < $0.03/day

---

## 12. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| LLM costs spiral | Cluster-level caching, cheap model for Pass 1 |
| Source blocks scraper | RSS-first, respect robots.txt, rotate user agents |
| Clustering quality poor | Start with threshold, upgrade to HDBSCAN, manual review dashboard |
| Email deliverability | Use Resend/Postmark, SPF/DKIM setup, warm domain |
| Auth complexity | Use Clerk/Supabase, don't roll own |

---

## 13. File Structure (Suggested)

```
ai-news-aggregator/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app
│   │   ├── config.py               # Settings
│   │   ├── database.py             # Postgres connection
│   │   ├── models/                 # SQLAlchemy models
│   │   ├── routers/                # API endpoints
│   │   ├── services/
│   │   │   ├── ingestion/          # Source fetchers
│   │   │   │   ├── arxiv.py
│   │   │   │   ├── hackernews.py
│   │   │   │   ├── rss.py
│   │   │   ├── processing/         # Pipeline
│   │   │   │   ├── dedup.py
│   │   │   │   ├── cluster.py
│   │   │   │   ├── rank.py
│   │   │   ├── llm/                # LLM calls
│   │   │   │   ├── summarize.py
│   │   │   │   ├── analyze.py
│   │   │   ├── delivery/           # Email, etc.
│   │   │   │   ├── email.py
│   │   │   └── billing/            # Stripe
│   │   └── workers/                # Celery tasks
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── app/                        # Next.js app router
│   ├── components/
│   ├── lib/
│   └── package.json
├── docker-compose.yml              # Local dev
├── .env.example
└── README.md
```

---

## 14. Key Decisions Already Made

1. **Python + FastAPI** — Not Node.js. NLP ecosystem matters more here.
2. **PostgreSQL + pgvector** — Not Pinecone/Weaviate. One database, simpler ops.
3. **Celery + Redis** — Not BullMQ. Python-native.
4. **Clerk/Supabase Auth** — Not custom auth.
5. **Stripe** — Not LemonSqueezy/Paddle. More control, standard.
6. **Cluster-level caching** — Not per-user analysis. Cost control is existential.
7. **Skip Twitter/X** — API costs kill MVP economics.

---

*End of specification. Build the MVP in the order specified. Do not add features beyond Week 4 scope.*
