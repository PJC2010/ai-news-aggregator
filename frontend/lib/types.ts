export type Topic = { id: string; label: string };
export type Profile = {
  id: string;
  email: string;
  subscription_tier: "free" | "pro";
  topic_limit: number;
  topics: string[];
  available_topics: Topic[];
};
export type Analysis = {
  event_type: string;
  technical_significance: number;
  who_should_care: string[];
  why_it_matters: string;
  what_to_watch: string;
  code_paper_links: string[];
  hype_check: "overhyped" | "underhyped" | "accurate";
};
export type RankComponent = {
  value: number;
  points?: number;
  available?: boolean;
  score?: number | null;
};
export type NewsEvent = {
  id: string;
  topic: string;
  cluster_size: number;
  primary_article: {
    id: string;
    title: string;
    url: string;
    published_at: string | null;
  };
  summary: string | null;
  analysis: Analysis | null;
  analysis_status: string;
  analyzed_at: string | null;
  significance_score: number | null;
  event_type: string | null;
  latest_published_at: string;
  created_at: string;
  rank_score: number;
  rank_version: string;
  rank_components: Record<string, RankComponent>;
  coverage?: {
    article_id: string;
    title: string;
    source: string;
    source_category: string;
    url: string;
  }[];
};
export type Feed = {
  total: number;
  limit: number;
  offset: number;
  sort: string;
  items: NewsEvent[];
  as_of: string;
  window: string;
  timezone: string;
};
export type Filters = {
  q: string;
  topic: string;
  following: boolean;
  window: "week" | "today" | "all";
  sort: "ranked" | "latest";
  event_type: string;
  page: number;
};
