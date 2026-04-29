export type Filters = {
  team?: string[];
  project?: string[];
  model?: string[];
  seniority?: string[];
  quarter?: string[];
  sprint?: string[];
};

export type Summary = {
  total_commits: number;
  total_spend: number;
  avg_cost_per_commit: number;
  avg_performance_score: number;
  avg_lead_time_hours: number;
  avg_bug_fix_count: number;
  cost_per_performance_point: number;
  best_model_by_roi: string | null;
};

export type BreakdownItem = {
  dimension: string;
  value: string;
  commits: number;
  usage_pct: number;
  estimated_spend: number;
  api_spend: number;
  api_spend_pct: number;
  subscription_spend: number;
  subscription_spend_pct: number;
  estimated_tokens: number;
  api_tokens: number;
  api_tokens_pct: number;
  subscription_tokens: number;
  subscription_tokens_pct: number;
  avg_performance_score: number;
  avg_longevity_days: number;
  avg_bug_fix_count: number;
  avg_iterations_raw: number;
  avg_longevity_score: number;
  avg_bug_fix_score: number;
  avg_lead_time_score: number;
  avg_iterations_score: number;
  roi_score: number;
  avg_lead_time_hours: number;
  avg_cost_per_commit: number;
  cost_per_performance_point: number;
  vs_human_performance_delta?: number | null;
  vs_human_longevity_days_delta?: number | null;
  vs_human_bug_fix_count_delta?: number | null;
  vs_human_lead_time_hours_delta?: number | null;
  vs_human_iterations_raw_delta?: number | null;
  vs_human_roi_delta?: number | null;
};

export type OptionsPayload = {
  teams: string[];
  projects: string[];
  team_projects: Record<string, string[]>;
  quarter_sprints: Record<string, string[]>;
  models: string[];
  seniority_levels: string[];
  quarters: string[];
  sprints: string[];
};

export type AIItem = Record<string, string | number | null>;

export type DataSourceInfo = {
  filename: string;
  records: number;
  size_bytes: number;
  updated_at: string;
};

export type TrendPoint = {
  label: string;
  estimated_spend: number;
  commits: number;
  avg_performance_score: number;
  api_spend: number;
  api_spend_pct: number;
  subscription_spend: number;
  subscription_spend_pct: number;
};

export type TrendPayload = {
  mode: "quarterly" | "quarter_sprints" | "sprint_daily";
  title: string;
  points: TrendPoint[];
};
