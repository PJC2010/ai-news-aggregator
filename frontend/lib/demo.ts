import type { Feed, Filters, NewsEvent, Profile } from "./types";

export const demoProfile: Profile = {
  id: "00000000-0000-4000-8000-000000000001",
  email: "reader@example.com",
  subscription_tier: "free",
  topic_limit: 3,
  topics: ["llm", "agents", "research"],
  available_topics: [
    { id: "llm", label: "Language models" },
    { id: "agents", label: "AI agents" },
    { id: "vision", label: "Computer vision" },
    { id: "open_source", label: "Open source" },
    { id: "research", label: "Research" },
    { id: "policy", label: "AI policy" },
    { id: "robotics", label: "Robotics" },
    { id: "infrastructure", label: "Infrastructure" },
  ],
};
// Entirely illustrative sample events, never a fallback for a live request.
const seeds = [
  [
    "A smaller language model, built for a longer train of thought",
    "model_release",
    "llm",
    "A sample research team releases an open-weight model focused on multi-step reasoning. Its report compares accuracy, latency, and memory use under the same inference budget. Independent replication is still needed.",
    9,
  ],
  [
    "AI agents learn when to ask for help",
    "paper",
    "agents",
    "An illustrative paper studies when an agent should hand a task back to a person. It measures completion rates alongside the cost of unnecessary interruptions. The result highlights the importance of evaluating human oversight.",
    8,
  ],
  [
    "The next computer vision benchmark moves beyond static images",
    "paper",
    "vision",
    "This sample benchmark asks models to follow objects through long video sequences. It includes difficult changes in lighting, viewpoint, and timing. A public evaluation protocol makes comparisons easier to reproduce.",
    8,
  ],
  [
    "An open-source toolkit makes inference costs easier to compare",
    "tool_release",
    "infrastructure",
    "A fictional developer toolkit reports throughput and memory use across serving configurations. It separates prefill and generation time. Hardware and workload details accompany each result.",
    7,
  ],
  [
    "A closer look at the evidence behind AI safety evaluations",
    "regulation",
    "policy",
    "An illustrative policy brief compares the scope of common safety evaluations. It distinguishes observed failures from broader claims about deployment risk. Its recommendations emphasize transparent reporting.",
    7,
  ],
  [
    "Robotics research tests a more general approach to manipulation",
    "research_breakthrough",
    "robotics",
    "A sample robotics experiment evaluates manipulation across unfamiliar objects. The reported gains depend on the number of demonstrations provided. Real-world reliability remains an open question.",
    8,
  ],
  [
    "Open-weight models get a reproducible evaluation recipe",
    "tool_release",
    "open_source",
    "A fictional release provides scripts for running comparable evaluations. It records model revision, prompt settings, and hardware. The authors caution against treating a single score as a complete assessment.",
    7,
  ],
  [
    "Why retrieval quality still shapes language model performance",
    "paper",
    "llm",
    "An illustrative study compares document selection with larger context windows. The experiments track answer accuracy and citation coverage. Better source selection matters as much as the volume of retrieved text.",
    7,
  ],
  [
    "A shared testbed for multi-agent coordination",
    "tool_release",
    "agents",
    "A sample environment evaluates how agents divide tasks and recover from errors. It includes repeatable tasks with explicit communication budgets. The testbed is intended to support comparisons across coordination strategies.",
    6,
  ],
  [
    "Research note: measuring what a benchmark misses",
    "paper",
    "research",
    "This illustrative research note examines how test construction affects reported progress. It uses controlled changes in task wording. The examples show why benchmark scores need context.",
    6,
  ],
  [
    "New serving patterns reduce idle GPU time",
    "tool_release",
    "infrastructure",
    "A fictional systems team reports experiments with batched workloads. It measures tail latency as well as average utilization. The results depend on traffic patterns and the chosen hardware.",
    6,
  ],
  [
    "An open-source collection of small, inspectable agent tasks",
    "tool_release",
    "open_source",
    "This sample collection emphasizes tasks that can be reviewed by a person. Each task has a documented goal and observable completion conditions. It is designed for debugging rather than leaderboard claims.",
    6,
  ],
  [
    "Language model compression without a single headline score",
    "paper",
    "llm",
    "An illustrative paper evaluates compressed models across several task families. It reports the effect on memory, latency, and accuracy separately. Some workloads benefit more than others.",
    5,
  ],
  [
    "A framework for reporting vision model limitations",
    "paper",
    "vision",
    "A fictional research team proposes a structured reporting template. It documents failure cases alongside successful examples. The aim is to make model behavior easier to assess before deployment.",
    5,
  ],
] as const;
export const demoEvents: NewsEvent[] = seeds.map((seed, index) => {
  const [title, kind, topic, summary, score] = seed;
  const date = new Date(Date.now() - (index * 3 + 1) * 3_600_000).toISOString();
  const id = `00000000-0000-4000-8000-${String(index + 10).padStart(12, "0")}`;
  const pending = index === 10;
  const count = index === 0 ? 4 : (index % 3) + 1;
  return {
    id,
    topic,
    cluster_size: count,
    primary_article: {
      id,
      title,
      url: `https://example.com/research/${index + 1}`,
      published_at: date,
    },
    summary: pending ? null : summary,
    analysis_status: pending ? "pending" : "ready",
    analyzed_at: pending ? null : date,
    significance_score: pending ? null : score,
    event_type: pending ? null : kind,
    latest_published_at: date,
    created_at: date,
    rank_score: 76 - index * 3.8,
    rank_version: "illustrative-demo",
    rank_components: {
      technical_significance: {
        value: score / 10,
        points: 35,
        available: !pending,
        score: pending ? null : score,
      },
      diversity: { value: 0.6, points: 18 },
      engagement: { value: 0.4, points: 10 },
      recency: { value: 0.8 },
    },
    analysis: pending
      ? null
      : {
          event_type: kind,
          technical_significance: score,
          who_should_care:
            index === 0
              ? ["ML engineers", "Technical founders"]
              : ["AI researchers", "ML engineers"],
          why_it_matters:
            index === 0
              ? "Smaller models can make reasoning workloads more practical on limited hardware. The meaningful comparison is the quality achieved at a fixed latency and memory budget, rather than parameter count alone."
              : "This sample illustrates how a shared event analysis connects a technical result to a practical decision. Evaluate the methods and limitations in the original material before applying its conclusions.",
          what_to_watch:
            index === 0
              ? "Watch for independent evaluations on unfamiliar tasks, full serving-cost measurements, and clarity on the model's license before planning a deployment."
              : "Look for independent replication, detailed evaluation settings, and evidence that the result transfers to a real workload.",
          code_paper_links: ["https://example.com/sample-material"],
          hype_check: "accurate",
        },
    coverage: Array.from({ length: count }, (_, i) => ({
      article_id: `${id}-${i}`,
      title: i === 0 ? title : `Supporting perspective ${i}`,
      source: i === 0 ? "Example Research" : `Example Publisher ${i}`,
      source_category: i === 0 ? "research" : "press",
      url: `https://example.com/coverage/${index}/${i}`,
    })),
  };
});
export function demoFeed(filters: Filters, topics: string[]): Feed {
  const now = new Date();
  let events = demoEvents.filter(
    (item) =>
      (!filters.q ||
        `${item.primary_article.title} ${item.summary || ""}`
          .toLowerCase()
          .includes(filters.q.toLowerCase())) &&
      (!filters.topic || item.topic === filters.topic) &&
      (!filters.following || topics.includes(item.topic)) &&
      (!filters.event_type || item.event_type === filters.event_type) &&
      (filters.window !== "today" ||
        item.latest_published_at.slice(0, 10) ===
          now.toISOString().slice(0, 10)),
  );
  events = [...events].sort(
    filters.sort === "latest"
      ? (a, b) => b.latest_published_at.localeCompare(a.latest_published_at)
      : (a, b) => b.rank_score - a.rank_score,
  );
  const offset = (filters.page - 1) * 12;
  return {
    total: events.length,
    items: events.slice(offset, offset + 12),
    offset,
    limit: 12,
    sort: filters.sort,
    as_of: now.toISOString(),
    window: filters.window,
    timezone: "UTC",
  };
}
