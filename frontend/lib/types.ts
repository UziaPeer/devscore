export type Filters = {
  team?: string[];
  project?: string[];
  model?: string[];
  seniority?: string[];
  quarter?: string;
  sprint?: string;
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
  avg_performance_score: number;
  avg_lead_time_hours: number;
  avg_cost_per_commit: number;
  cost_per_performance_point: number;
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
};

export type TrendPayload = {
  mode: "quarterly" | "quarter_sprints" | "sprint_daily";
  title: string;
  points: TrendPoint[];
};
