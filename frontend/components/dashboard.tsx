"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Bot, ChartNoAxesCombined, ChevronDown, Coins, FileUp, Filter, MessageSquareText, Sparkles } from "lucide-react";

import { getBreakdown, getDataSource, getOptions, getSummary, getTrend, postAI, uploadDataSource } from "../lib/api";
import type { AIItem, BreakdownItem, DataSourceInfo, Filters, OptionsPayload, Summary, TrendPayload } from "../lib/types";

const emptySummary: Summary = {
  total_commits: 0,
  total_spend: 0,
  avg_cost_per_commit: 0,
  avg_performance_score: 0,
  avg_lead_time_hours: 0,
  avg_bug_fix_count: 0,
  cost_per_performance_point: 0,
  best_model_by_roi: null
};

type ModelMetricTab =
  | "longevity"
  | "bugfix"
  | "leadtime"
  | "iterations"
  | "cost"
  | "performance"
  | "roi";

const MODEL_METRIC_CONFIG: Record<
  ModelMetricTab,
  {
    label: string;
    title: string;
    dataKey:
      | "avg_longevity_days"
      | "avg_bug_fix_count"
      | "avg_lead_time_hours"
      | "avg_iterations_raw"
      | "estimated_spend"
      | "avg_performance_score"
      | "roi_score";
    higherIsBetter: boolean;
    deltaKey?:
      | "vs_human_longevity_days_delta"
      | "vs_human_bug_fix_count_delta"
      | "vs_human_lead_time_hours_delta"
      | "vs_human_iterations_raw_delta"
      | "vs_human_performance_delta"
      | "vs_human_roi_delta";
    yFormatter?: (value: number) => string;
    valueFormatter?: (value: number) => string;
    tooltip: string;
  }
> = {
  longevity: {
    label: "Longevity",
    title: "Average Longevity (Days) by Model",
    dataKey: "avg_longevity_days",
    higherIsBetter: true,
    deltaKey: "vs_human_longevity_days_delta",
    yFormatter: (value) => `${value.toFixed(1)}d`,
    valueFormatter: (value) => `${value.toFixed(1)} days`,
    tooltip:
      "Average days before code is overridden. Compared to Human baseline. Higher is better. This metric contributes 35% to Performance."
  },
  bugfix: {
    label: "Bug Fix",
    title: "Average Bug-Fix Overrides by Model",
    dataKey: "avg_bug_fix_count",
    higherIsBetter: false,
    deltaKey: "vs_human_bug_fix_count_delta",
    valueFormatter: (value) => value.toFixed(2),
    tooltip:
      "Average bug-fix overrides per commit. Compared to Human baseline. Lower is better. This metric contributes 30% to Performance."
  },
  leadtime: {
    label: "Lead Time",
    title: "Average Lead Time (Hours) by Model",
    dataKey: "avg_lead_time_hours",
    higherIsBetter: false,
    deltaKey: "vs_human_lead_time_hours_delta",
    yFormatter: (value) => `${value.toFixed(1)}h`,
    valueFormatter: (value) => `${value.toFixed(1)} hours`,
    tooltip:
      "Average time to merge (hours). Compared to Human baseline. Lower is better. This metric contributes 20% to Performance."
  },
  iterations: {
    label: "Iterations",
    title: "Average PR Iterations by Model",
    dataKey: "avg_iterations_raw",
    higherIsBetter: false,
    deltaKey: "vs_human_iterations_raw_delta",
    valueFormatter: (value) => value.toFixed(2),
    tooltip:
      "Average review friction (revisions + comments/4). Compared to Human baseline. Lower is better. This metric contributes 15% to Performance."
  },
  cost: {
    label: "Cost",
    title: "Estimated Cost by Model",
    dataKey: "estimated_spend",
    higherIsBetter: false,
    yFormatter: (value) => `$${value.toFixed(3)}`,
    valueFormatter: (value) => `$${value.toFixed(3)}`,
    tooltip:
      "If the developer has a subscription to this model, we use their subscription cost. If not, we charge by usage. Bigger commits cost more in usage mode. Lower is better."
  },
  performance: {
    label: "Performance",
    title: "Performance Score by Model",
    dataKey: "avg_performance_score",
    higherIsBetter: true,
    deltaKey: "vs_human_performance_delta",
    valueFormatter: (value) => value.toFixed(2),
    tooltip:
      "Final weighted performance compared to Human baseline. Formula weights: Longevity 35%, Bug Fix 30%, Lead Time 20%, Iterations 15%. Higher is better."
  },
  roi: {
    label: "ROI",
    title: "ROI by Model",
    dataKey: "roi_score",
    higherIsBetter: true,
    deltaKey: "vs_human_roi_delta",
    valueFormatter: (value) => value.toFixed(2),
    tooltip:
      "Performance gained per spend, compared to Human baseline. Higher is better."
  }
};

const MODEL_BAR_COLORS: Record<string, string> = {
  claude: "#DE7356",
  gemini: "#4796E3",
  codellama: "#0668E1",
  "code-llama": "#0668E1",
  llama: "#0668E1",
  "gpt-4": "#00A67E",
  "gpt4": "#00A67E",
  "gpt-3.5": "#00A67E",
  "gpt3.5": "#00A67E",
  "gpt-35": "#00A67E",
  human: "#8A8F99"
};

const MODEL_LOGO_URLS: Record<string, string> = {
  claude: "https://upload.wikimedia.org/wikipedia/commons/b/b0/Claude_AI_symbol.svg",
  gemini: "https://upload.wikimedia.org/wikipedia/commons/1/1d/Google_Gemini_icon_2025.svg",
  codellama: "https://upload.wikimedia.org/wikipedia/commons/d/d0/Meta_Platforms_logo.svg",
  "code-llama": "https://upload.wikimedia.org/wikipedia/commons/d/d0/Meta_Platforms_logo.svg",
  llama: "https://upload.wikimedia.org/wikipedia/commons/d/d0/Meta_Platforms_logo.svg",
  "gpt-4": "https://upload.wikimedia.org/wikipedia/commons/0/04/ChatGPT_logo.svg",
  gpt4: "https://upload.wikimedia.org/wikipedia/commons/0/04/ChatGPT_logo.svg",
  "gpt-3.5": "https://upload.wikimedia.org/wikipedia/commons/0/04/ChatGPT_logo.svg",
  "gpt3.5": "https://upload.wikimedia.org/wikipedia/commons/0/04/ChatGPT_logo.svg",
  "gpt-35": "https://upload.wikimedia.org/wikipedia/commons/0/04/ChatGPT_logo.svg"
};

function getModelBarColor(modelName: string): string {
  const normalized = modelName.trim().toLowerCase();
  return MODEL_BAR_COLORS[normalized] ?? "var(--brand)";
}

function getModelLogoUrl(modelName: string): string | null {
  const normalized = modelName.trim().toLowerCase();
  return MODEL_LOGO_URLS[normalized] ?? null;
}

type AiPanelState = {
  insights: AIItem[];
  recommendations: AIItem[];
  categories: AIItem[];
  queryResults: AIItem[];
  model: string | null;
  loading: boolean;
  error: string | null;
};

function money(value: number): string {
  return `$${value.toFixed(4)}`;
}

function SelectField({
  label,
  value,
  options,
  onChange
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <label style={{ display: "grid", gap: 4, minWidth: 140 }}>
      <span style={{ fontSize: 12, color: "var(--text-muted)", fontWeight: 700 }}>{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        style={{
          height: 36,
          borderRadius: 8,
          border: "1px solid var(--border)",
          padding: "0 10px",
          backgroundColor: "var(--surface)"
        }}
      >
        <option value="">All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function MultiCheckboxField({
  label,
  values,
  options,
  onChange
}: {
  label: string;
  values: string[];
  options: string[];
  onChange: (values: string[]) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function onDocumentClick(event: MouseEvent) {
      if (!wrapperRef.current) {
        return;
      }
      if (!wrapperRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    document.addEventListener("mousedown", onDocumentClick);
    return () => document.removeEventListener("mousedown", onDocumentClick);
  }, []);

  const buttonText = values.length === 0 ? "All" : values.length === 1 ? values[0] : `${values.length} selected`;

  return (
    <div ref={wrapperRef} style={{ position: "relative", minWidth: 140 }}>
      <label style={{ display: "grid", gap: 4 }}>
        <span style={{ fontSize: 12, color: "var(--text-muted)", fontWeight: 700 }}>{label}</span>
      </label>
      <button
        type="button"
        onClick={() => setIsOpen((previous) => !previous)}
        style={{
          width: "100%",
          height: 36,
          borderRadius: 8,
          border: "1px solid var(--border)",
          padding: "0 10px",
          backgroundColor: "var(--surface)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          cursor: "pointer",
          color: "var(--text)",
          fontSize: 14
        }}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{buttonText}</span>
        <ChevronDown size={15} color="var(--text-muted)" />
      </button>
      {isOpen && (
        <div
          style={{
            position: "absolute",
            top: 44,
            left: 0,
            right: 0,
            zIndex: 40,
            border: "1px solid var(--border)",
            borderRadius: 8,
            backgroundColor: "var(--surface)",
            boxShadow: "0 8px 20px rgba(24, 38, 29, 0.12)",
            maxHeight: 220,
            overflow: "auto",
            padding: 8,
            display: "grid",
            gap: 6
          }}
        >
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer", paddingBottom: 4, borderBottom: "1px solid var(--border)" }}>
            <input
              type="checkbox"
              checked={values.length === 0}
              onChange={() => {
                onChange([]);
              }}
            />
            <span>All</span>
          </label>
          {options.map((option) => {
            const checked = values.includes(option);
            return (
              <label key={option} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(event) => {
                    const nextSet = new Set(values);
                    if (event.target.checked) {
                      nextSet.add(option);
                    } else {
                      nextSet.delete(option);
                    }
                    onChange(Array.from(nextSet));
                  }}
                />
                <span>{option}</span>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}

function KpiCard({
  title,
  value,
  icon
}: {
  title: string;
  value: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="panel" style={{ padding: 14, minHeight: 90 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <span style={{ fontWeight: 700, color: "var(--text-muted)", fontSize: 12, letterSpacing: 0.4 }}>{title}</span>
        <span style={{ color: "var(--brand-dark)" }}>{icon}</span>
      </div>
      <div style={{ fontWeight: 800, fontSize: 26, color: "var(--text)" }}>{value}</div>
    </div>
  );
}

function extractMessage(aiItem: AIItem): string {
  const text = aiItem.finding ?? aiItem.answer ?? aiItem.rationale ?? aiItem.reason ?? aiItem.action;
  return typeof text === "string" ? text : JSON.stringify(aiItem);
}

function formatDelta(value: number, formatter?: (value: number) => string): string {
  const sign = value > 0 ? "+" : "";
  if (formatter) {
    return `${sign}${formatter(value)}`;
  }
  return `${sign}${value.toFixed(2)}`;
}

function ModelAxisTick({
  x = 0,
  y = 0,
  payload
}: {
  x?: number;
  y?: number;
  payload?: { value?: string };
}) {
  const label = payload?.value ?? "";
  const logoUrl = getModelLogoUrl(label);
  const normalized = label.trim().toLowerCase();
  const isHuman = normalized === "human";
  const logoSize = 20;

  return (
    <g transform={`translate(${x},${y})`}>
      <text x={0} y={14} textAnchor="middle" fill="var(--text-muted)" fontSize={11}>
        {label}
      </text>
      {isHuman && (
        <g transform="translate(-10,20)">
          <circle cx="10" cy="4.5" r="4" fill="none" stroke="#111111" strokeWidth="1.6" />
          <path d="M3.2,18.8 L16.8,18.8 L16.1,10.8 L12.6,9.1 L7.4,9.1 L3.9,10.8 Z" fill="none" stroke="#111111" strokeWidth="1.6" strokeLinejoin="round" />
          <path d="M8.7,10 L11.3,10 L10.5,12.1 L10.5,18.8 L9.5,18.8 L9.5,12.1 Z" fill="#5f97a8" stroke="#111111" strokeWidth="0.9" strokeLinejoin="round" />
        </g>
      )}
      {!isHuman && logoUrl && <image href={logoUrl} x={-logoSize / 2} y={20} width={logoSize} height={logoSize} />}
    </g>
  );
}

export function Dashboard() {
  const [filters, setFilters] = useState<Filters>({});
  const [reloadTick, setReloadTick] = useState(0);
  const hiddenFileInputRef = useRef<HTMLInputElement | null>(null);
  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const [dataSource, setDataSource] = useState<DataSourceInfo | null>(null);
  const [options, setOptions] = useState<OptionsPayload>({
    teams: [],
    projects: [],
    team_projects: {},
    quarter_sprints: {},
    models: [],
    seniority_levels: [],
    quarters: [],
    sprints: []
  });

  const [summary, setSummary] = useState<Summary>(emptySummary);
  const [byModel, setByModel] = useState<BreakdownItem[]>([]);
  const [trend, setTrend] = useState<TrendPayload>({ mode: "quarterly", title: "Quarterly Spend Trend", points: [] });
  const [byProject, setByProject] = useState<BreakdownItem[]>([]);
  const [modelChartTab, setModelChartTab] = useState<ModelMetricTab>("roi");
  const [backendError, setBackendError] = useState<string | null>(null);
  const [query, setQuery] = useState("Which project has the worst cost per performance point?");
  const [aiState, setAiState] = useState<AiPanelState>({
    insights: [],
    recommendations: [],
    categories: [],
    queryResults: [],
    model: null,
    loading: false,
    error: null
  });
  const [activeAiTab, setActiveAiTab] = useState<"insights" | "recommendations" | "queryResults" | "categories">("insights");

  useEffect(() => {
    Promise.all([getOptions(), getDataSource()])
      .then(([optionPayload, sourcePayload]) => {
        setOptions(optionPayload);
        setDataSource(sourcePayload);
      })
      .catch((error) => {
        setBackendError(`Backend setup failed: ${String(error)}`);
      });
  }, [reloadTick]);

  useEffect(() => {
    Promise.all([getSummary(filters), getBreakdown("model", filters), getTrend(filters), getBreakdown("project", filters)])
      .then(([summaryPayload, modelBreakdown, trendPayload, projectBreakdown]) => {
        setSummary(summaryPayload);
        setByModel(modelBreakdown);
        setTrend(trendPayload);
        setByProject(projectBreakdown);
        setBackendError(null);
      })
      .catch((error) => {
        setBackendError(`Backend analytics failed: ${String(error)}`);
      });
  }, [filters, reloadTick]);

  const lineData = useMemo(() => trend.points, [trend.points]);
  const modelChartConfig = MODEL_METRIC_CONFIG[modelChartTab];
  const sortedModelData = useMemo(() => {
    const dataKey = modelChartConfig.dataKey;
    const direction = modelChartConfig.higherIsBetter ? -1 : 1;
    const hideHumanTabs: ModelMetricTab[] = ["cost", "roi"];
    const modelRows = hideHumanTabs.includes(modelChartTab) ? byModel.filter((row) => row.value !== "Human") : byModel;
    return [...modelRows].sort((left, right) => {
      const leftValue = Number(left[dataKey]);
      const rightValue = Number(right[dataKey]);
      return (leftValue - rightValue) * direction;
    });
  }, [byModel, modelChartConfig.dataKey, modelChartConfig.higherIsBetter, modelChartTab]);
  const trendTitle = useMemo(() => {
    if (trend.title.includes("Spend & Performance")) {
      return trend.title;
    }
    return trend.title.replace("Spend", "Spend & Performance");
  }, [trend.title]);
  const projectOptions = useMemo(() => {
    const selectedTeams = filters.team ?? [];
    if (selectedTeams.length === 0) {
      return options.projects;
    }
    const union = new Set<string>();
    selectedTeams.forEach((teamName) => {
      (options.team_projects[teamName] ?? []).forEach((projectName) => union.add(projectName));
    });
    return Array.from(union).sort();
  }, [filters.team, options.projects, options.team_projects]);
  const sprintOptions = useMemo(() => {
    const selectedQuarters = filters.quarter ?? [];
    if (selectedQuarters.length === 0) {
      return options.sprints;
    }
    const union = new Set<string>();
    selectedQuarters.forEach((quarterName) => {
      (options.quarter_sprints[quarterName] ?? []).forEach((sprintName) => union.add(sprintName));
    });
    return Array.from(union).sort((left, right) => {
      const leftNumber = Number.parseInt(left.replace("Sprint ", ""), 10);
      const rightNumber = Number.parseInt(right.replace("Sprint ", ""), 10);
      if (Number.isNaN(leftNumber) || Number.isNaN(rightNumber)) {
        return left.localeCompare(right);
      }
      return leftNumber - rightNumber;
    });
  }, [filters.quarter, options.sprints, options.quarter_sprints]);

  useEffect(() => {
    const selectedProjects = filters.project ?? [];
    if (selectedProjects.length === 0) {
      return;
    }
    const validProjects = selectedProjects.filter((projectName) => projectOptions.includes(projectName));
    if (validProjects.length === selectedProjects.length) {
      return;
    }
    setFilters((previous) => ({ ...previous, project: validProjects.length ? validProjects : undefined }));
  }, [filters.project, projectOptions]);

  useEffect(() => {
    const selectedSprints = filters.sprint ?? [];
    if (selectedSprints.length === 0) {
      return;
    }
    const validSprints = selectedSprints.filter((sprintName) => sprintOptions.includes(sprintName));
    if (validSprints.length === selectedSprints.length) {
      return;
    }
    setFilters((previous) => ({ ...previous, sprint: validSprints.length ? validSprints : undefined }));
  }, [filters.sprint, sprintOptions]);

  async function runAiActions() {
    setAiState((previous) => ({ ...previous, loading: true, error: null }));
    try {
      const [insights, recommendations, categories, queryResults] = await Promise.all([
        postAI("/ai/insights", filters),
        postAI("/ai/recommendations", filters),
        postAI("/ai/categorize", filters),
        postAI("/ai/query", { ...filters, question: query })
      ]);

      setAiState({
        insights: insights.items,
        recommendations: recommendations.items,
        categories: categories.items.slice(0, 5),
        queryResults: queryResults.items,
        model: insights.model,
        loading: false,
        error: null
      });
    } catch (error) {
      setAiState((previous) => ({
        ...previous,
        loading: false,
        error: String(error)
      }));
    }
  }

  async function handleUpload(file: File) {
    setUploadLoading(true);
    setUploadError(null);
    setUploadMessage(null);
    try {
      const source = await uploadDataSource(file);
      setDataSource(source);
      setReloadTick((value) => value + 1);
      setUploadMessage(`Uploaded ${source.filename}. Dashboard data refreshed.`);
    } catch (error) {
      setUploadError(String(error));
    } finally {
      setUploadLoading(false);
    }
  }

  function openFilePicker() {
    hiddenFileInputRef.current?.click();
  }

  function onFileSelected(event: React.ChangeEvent<HTMLInputElement>) {
    const selectedFile = event.target.files?.[0];
    if (!selectedFile) {
      return;
    }
    void handleUpload(selectedFile);
    event.target.value = "";
  }

  return (
    <main className="page-shell">
      <section
        style={{
          display: "flex",
          justifyContent: "flex-start",
          alignItems: "center",
          marginBottom: 10,
          paddingLeft: 2
        }}
      >
        <img
          src="https://www.etoro.com/wp-content/themes/etoro/assets/images/logo.svg"
          alt="eToro logo"
          style={{ width: 132, height: "auto", display: "block" }}
        />
      </section>

      <section
        className="panel"
        style={{
          display: "flex",
          justifyContent: "flex-start",
          alignItems: "center",
          padding: "16px 20px",
          marginBottom: 12
        }}
      >
        <div>
          <div style={{ fontSize: 13, color: "var(--brand-dark)", fontWeight: 800 }}>DevScore</div>
          <h1 style={{ margin: "4px 0 0", fontSize: 24 }}>AI Cost & PR Outcome Intelligence</h1>
        </div>
      </section>

      {backendError && (
        <section className="panel" style={{ padding: 12, marginBottom: 12, borderColor: "var(--danger)" }}>
          <strong style={{ color: "var(--danger)" }}>Backend error:</strong> {backendError}
        </section>
      )}

      <div className="filters-layout">
        <section className="panel" style={{ padding: 12 }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10 }}>
            <Filter size={14} color="var(--text-muted)" />
            <strong style={{ fontSize: 13 }}>Filters</strong>
          </div>
          <div className="filter-controls">
            <MultiCheckboxField
              label="Team"
              values={filters.team ?? []}
              options={options.teams}
              onChange={(nextTeams) => {
                const teamValues = nextTeams.length ? nextTeams : undefined;
                setFilters((previous) => {
                  const allowedProjects = new Set<string>();
                  (teamValues ?? []).forEach((teamName) => {
                    (options.team_projects[teamName] ?? []).forEach((projectName) => allowedProjects.add(projectName));
                  });
                  const currentProjects = previous.project ?? [];
                  const filteredProjects = teamValues
                    ? currentProjects.filter((projectName) => allowedProjects.has(projectName))
                    : currentProjects;
                  return {
                    ...previous,
                    team: teamValues,
                    project: filteredProjects.length ? filteredProjects : undefined
                  };
                });
              }}
            />
            <MultiCheckboxField
              label="Project"
              values={filters.project ?? []}
              options={projectOptions}
              onChange={(value) => setFilters((prev) => ({ ...prev, project: value.length ? value : undefined }))}
            />
            <MultiCheckboxField
              label="Model"
              values={filters.model ?? []}
              options={options.models}
              onChange={(value) => setFilters((prev) => ({ ...prev, model: value.length ? value : undefined }))}
            />
            <MultiCheckboxField
              label="Seniority"
              values={filters.seniority ?? []}
              options={options.seniority_levels}
              onChange={(value) => setFilters((prev) => ({ ...prev, seniority: value.length ? value : undefined }))}
            />
            <MultiCheckboxField
              label="Quarter"
              values={filters.quarter ?? []}
              options={options.quarters}
              onChange={(nextQuarters) => {
                const quarterValues = nextQuarters.length ? nextQuarters : undefined;
                setFilters((previous) => {
                  if (!quarterValues) {
                    return { ...previous, quarter: undefined };
                  }
                  const allowedSprints = new Set<string>();
                  quarterValues.forEach((quarterName) => {
                    (options.quarter_sprints[quarterName] ?? []).forEach((sprintName) => allowedSprints.add(sprintName));
                  });
                  const currentSprints = previous.sprint ?? [];
                  const filteredSprints = currentSprints.filter((sprintName) => allowedSprints.has(sprintName));
                  return {
                    ...previous,
                    quarter: quarterValues,
                    sprint: filteredSprints.length ? filteredSprints : undefined
                  };
                });
              }}
            />
            <MultiCheckboxField
              label="Sprint"
              values={filters.sprint ?? []}
              options={sprintOptions}
              onChange={(value) => setFilters((prev) => ({ ...prev, sprint: value.length ? value : undefined }))}
            />
          </div>
        </section>
        <section
          className="panel data-source-compact"
          style={{
            padding: 12,
            display: "grid",
            gap: 8,
            alignContent: "start"
          }}
        >
          <div style={{ fontWeight: 800, fontSize: 13 }}>Data Source</div>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            Current file: <strong style={{ color: "var(--text)" }}>{dataSource?.filename ?? "N/A"}</strong>
          </div>
          <input
            ref={hiddenFileInputRef}
            type="file"
            accept=".json,application/json"
            onChange={onFileSelected}
            style={{ display: "none" }}
          />
          <button
            type="button"
            onClick={openFilePicker}
            disabled={uploadLoading}
            style={{
              borderRadius: 8,
              border: "none",
              backgroundColor: uploadLoading ? "#9adfb3" : "var(--brand)",
              color: "white",
              fontWeight: 700,
              height: 34,
              padding: "0 12px",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 6,
              cursor: uploadLoading ? "not-allowed" : "pointer"
            }}
          >
            <FileUp size={15} />
            {uploadLoading ? "Uploading..." : "Upload & Replace"}
          </button>
          {uploadMessage && <div style={{ fontSize: 11, color: "var(--brand-dark)" }}>{uploadMessage}</div>}
          {uploadError && <div style={{ fontSize: 11, color: "var(--danger)" }}>{uploadError}</div>}
        </section>
      </div>

      <section className="kpi-grid">
        <KpiCard title="Estimated Spend" value={money(summary.total_spend)} icon={<Coins size={18} />} />
        <KpiCard title="Performance Score" value={summary.avg_performance_score.toFixed(2)} icon={<ChartNoAxesCombined size={18} />} />
        <KpiCard title="Cost / Performance Point" value={money(summary.cost_per_performance_point)} icon={<Coins size={18} />} />
        <KpiCard title="Best ROI Model" value={summary.best_model_by_roi ?? "N/A"} icon={<Bot size={18} />} />
      </section>

      <section className="chart-grid">
        <article className="panel" style={{ padding: 14, minHeight: 280 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <h3 style={{ margin: 0, fontSize: 16 }}>{modelChartConfig.title}</h3>
              <div className="metric-info-wrap">
                <span
                  style={{
                    fontSize: 12,
                    lineHeight: "18px",
                    width: 18,
                    height: 18,
                    borderRadius: 999,
                    border: "1px solid var(--border)",
                    textAlign: "center",
                    color: "var(--text-muted)",
                    cursor: "help",
                    userSelect: "none",
                    display: "inline-block",
                    backgroundColor: "var(--surface)"
                  }}
                >
                  ⓘ
                </span>
                <div className="metric-info-tooltip" role="tooltip" aria-label={modelChartConfig.title}>
                  <div className="metric-info-title">{modelChartConfig.title}</div>
                  <div className="metric-info-body">{modelChartConfig.tooltip}</div>
                </div>
              </div>
            </div>
            <div
              style={{
                display: "inline-flex",
                border: "1px solid var(--border)",
                borderRadius: 8,
                overflow: "hidden",
                backgroundColor: "var(--surface-muted)",
                flexWrap: "wrap",
                justifyContent: "flex-end"
              }}
            >
              {(Object.keys(MODEL_METRIC_CONFIG) as ModelMetricTab[]).map((tabKey) => (
                <button
                  key={tabKey}
                  type="button"
                  onClick={() => setModelChartTab(tabKey)}
                  style={{
                    border: "none",
                    height: 28,
                    padding: "0 10px",
                    fontSize: 12,
                    fontWeight: tabKey === "roi" ? 800 : 700,
                    cursor: "pointer",
                    backgroundColor: modelChartTab === tabKey ? "var(--surface)" : "transparent",
                    color: modelChartTab === tabKey ? "var(--text)" : "var(--text-muted)"
                  }}
                >
                  {MODEL_METRIC_CONFIG[tabKey].label}
                </button>
              ))}
            </div>
          </div>
          <div style={{ height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={sortedModelData}>
                <defs>
                  <linearGradient id="model-plot-fade" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="rgba(19, 198, 54, 0.14)" />
                    <stop offset="50%" stopColor="rgba(19, 198, 54, 0.045)" />
                    <stop offset="100%" stopColor="rgba(19, 198, 54, 0)" />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#dfe7e2" fill="url(#model-plot-fade)" />
                <XAxis dataKey="value" tick={<ModelAxisTick />} interval={0} height={52} />
                <YAxis tick={{ fontSize: 11 }} tickFormatter={modelChartConfig.yFormatter} />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (!active || !payload || payload.length === 0) {
                      return null;
                    }
                    const row = payload[0]?.payload as BreakdownItem | undefined;
                    if (!row) {
                      return null;
                    }
                    const rawValue = Number(row[modelChartConfig.dataKey]);
                    const formattedValue = modelChartConfig.valueFormatter
                      ? modelChartConfig.valueFormatter(rawValue)
                      : rawValue.toFixed(2);
                    const deltaKey = modelChartConfig.deltaKey;
                    const deltaValue = deltaKey ? row[deltaKey] : null;
                    return (
                      <div
                        style={{
                          backgroundColor: "white",
                          border: "1px solid var(--border)",
                          borderRadius: 8,
                          padding: "8px 10px",
                          boxShadow: "0 4px 14px rgba(0, 0, 33, 0.12)",
                          fontSize: 12
                        }}
                      >
                        <div style={{ fontWeight: 700, marginBottom: 4 }}>{label}</div>
                        <div style={{ color: "var(--text-muted)" }}>
                          {modelChartConfig.label}: {formattedValue}
                        </div>
                        {deltaKey && row.value !== "Human" && typeof deltaValue === "number" && (
                          <div style={{ color: "var(--text-muted)" }}>
                            vs Human: {formatDelta(deltaValue, modelChartConfig.valueFormatter)}
                          </div>
                        )}
                      </div>
                    );
                  }}
                />
                <Bar dataKey={modelChartConfig.dataKey} radius={[4, 4, 0, 0]}>
                  {sortedModelData.map((item) => (
                    <Cell key={`model-bar-${item.value}`} fill={getModelBarColor(item.value)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </article>
        <article className="panel" style={{ padding: 14, minHeight: 280 }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>{trendTitle}</h3>
          <div style={{ height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={lineData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#dfe7e2" />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                <YAxis yAxisId="spend" tick={{ fontSize: 11 }} />
                <YAxis yAxisId="performance" orientation="right" domain={[0, 100]} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Line type="monotone" dataKey="estimated_spend" yAxisId="spend" stroke="#D64141" strokeWidth={2} dot={{ r: 2 }} />
                <Line type="monotone" dataKey="avg_performance_score" yAxisId="performance" stroke="var(--brand-dark)" strokeWidth={2} dot={{ r: 2 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </article>
      </section>

      <section className="table-grid">
        <article className="panel" style={{ padding: 0, overflow: "hidden", minHeight: 520 }}>
          <div
            style={{
              padding: "16px 16px 14px",
              background:
                "linear-gradient(120deg, rgba(19, 198, 54, 0.18) 0%, rgba(19, 198, 54, 0.08) 45%, rgba(255, 255, 255, 0.95) 100%)",
              borderBottom: "1px solid var(--border)"
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 8 }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 21, lineHeight: 1.1, letterSpacing: 0.1 }}>AI Strategy Studio</h3>
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 6, maxWidth: 520, lineHeight: 1.4 }}>
                  Fast insights from your current filters.
                </div>
              </div>
              <button
                type="button"
                onClick={runAiActions}
                style={{
                  borderRadius: 8,
                  border: "none",
                  backgroundColor: "var(--brand)",
                  color: "white",
                  fontWeight: 700,
                  height: 38,
                  padding: "0 14px",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  cursor: "pointer",
                  whiteSpace: "nowrap"
                }}
              >
                <Sparkles size={16} />
                {aiState.loading ? "Running AI..." : "Run AI Analysis"}
              </button>
            </div>
          </div>

          <div style={{ padding: 14, display: "grid", gap: 12 }}>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 12, color: "var(--text-muted)", fontWeight: 700, display: "inline-flex", alignItems: "center", gap: 6 }}>
                <MessageSquareText size={14} /> Natural Language Question
              </span>
              <textarea
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                rows={3}
                style={{ resize: "vertical", border: "1px solid var(--border)", borderRadius: 8, padding: 10, backgroundColor: "var(--surface)" }}
              />
            </label>

            {aiState.error && (
              <div style={{ color: "var(--danger)", fontSize: 12, border: "1px solid #f2c9c9", backgroundColor: "#fff4f4", borderRadius: 8, padding: 8 }}>
                {aiState.error}
              </div>
            )}

            <div style={{ display: "inline-flex", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden", width: "fit-content" }}>
              {[
                { key: "insights", label: "Insights", count: aiState.insights.length },
                { key: "recommendations", label: "Recommendations", count: aiState.recommendations.length },
                { key: "queryResults", label: "Q&A", count: aiState.queryResults.length },
                { key: "categories", label: "Categories", count: aiState.categories.length }
              ].map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setActiveAiTab(tab.key as "insights" | "recommendations" | "queryResults" | "categories")}
                  style={{
                    border: "none",
                    backgroundColor: activeAiTab === tab.key ? "var(--brand)" : "var(--surface)",
                    color: activeAiTab === tab.key ? "white" : "var(--text)",
                    height: 32,
                    padding: "0 10px",
                    fontSize: 12,
                    fontWeight: 700,
                    cursor: "pointer"
                  }}
                >
                  {tab.label} ({tab.count})
                </button>
              ))}
            </div>

            <div
              style={{
                display: "grid",
                gap: 8,
                minHeight: 240,
                maxHeight: 320,
                overflow: "auto",
                border: "1px solid var(--border)",
                borderRadius: 10,
                padding: 10,
                backgroundColor: "var(--surface-muted)"
              }}
            >
              {(aiState[activeAiTab] as AIItem[]).length === 0 ? (
                <div style={{ fontSize: 12, color: "var(--text-muted)", padding: 8 }}>
                  No items yet for this section. Run AI Analysis to generate new results.
                </div>
              ) : (
                (aiState[activeAiTab] as AIItem[]).map((item, index) => (
                  <div
                    key={`${activeAiTab}-${index}`}
                    style={{
                      border: "1px solid var(--border)",
                      borderRadius: 8,
                      padding: "10px 10px",
                      fontSize: 12,
                      backgroundColor: "var(--surface)",
                      boxShadow: "0 1px 4px rgba(0, 0, 33, 0.05)"
                    }}
                  >
                    {extractMessage(item)}
                  </div>
                ))
              )}
            </div>
          </div>
        </article>

        <article className="panel" style={{ padding: 14 }}>
          <h3 style={{ margin: "0 0 10px", fontSize: 16 }}>Project Comparison</h3>
          <div style={{ overflow: "auto", maxHeight: 420 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ backgroundColor: "var(--surface-muted)" }}>
                  <th style={{ textAlign: "left", padding: 8 }}>Project</th>
                  <th style={{ textAlign: "right", padding: 8 }}>Spend</th>
                  <th style={{ textAlign: "right", padding: 8 }}>Perf</th>
                  <th style={{ textAlign: "right", padding: 8 }}>Cost/Perf</th>
                </tr>
              </thead>
              <tbody>
                {byProject.slice(0, 8).map((item) => (
                  <tr key={item.value} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: 8, fontWeight: 600 }}>{item.value}</td>
                    <td style={{ padding: 8, textAlign: "right" }}>{money(item.estimated_spend)}</td>
                    <td style={{ padding: 8, textAlign: "right" }}>{item.avg_performance_score.toFixed(2)}</td>
                    <td style={{ padding: 8, textAlign: "right" }}>{money(item.cost_per_performance_point)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      </section>
    </main>
  );
}
