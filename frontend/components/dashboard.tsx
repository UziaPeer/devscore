"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Bot, ChartNoAxesCombined, ChevronDown, Coins, FileUp, Filter, Sparkles } from "lucide-react";

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
    if (!filters.quarter) {
      return options.sprints;
    }
    return options.quarter_sprints[filters.quarter] ?? [];
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
    if (!filters.sprint) {
      return;
    }
    if (sprintOptions.includes(filters.sprint)) {
      return;
    }
    setFilters((previous) => ({ ...previous, sprint: undefined }));
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
        className="panel"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "16px 20px",
          marginBottom: 12
        }}
      >
        <div>
          <div style={{ fontSize: 13, color: "var(--brand-dark)", fontWeight: 800 }}>DevScore</div>
          <h1 style={{ margin: "4px 0 0", fontSize: 24 }}>AI Cost & PR Outcome Intelligence</h1>
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
            cursor: "pointer"
          }}
        >
          <Sparkles size={16} />
          {aiState.loading ? "Running AI..." : "Run AI Analysis"}
        </button>
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
            <SelectField
              label="Quarter"
              value={filters.quarter ?? ""}
              options={options.quarters}
              onChange={(value) => {
                const nextQuarter = value || undefined;
                setFilters((previous) => {
                  const nextSprintOptions = nextQuarter ? options.quarter_sprints[nextQuarter] ?? [] : options.sprints;
                  const nextSprint = previous.sprint && nextSprintOptions.includes(previous.sprint) ? previous.sprint : undefined;
                  return { ...previous, quarter: nextQuarter, sprint: nextSprint };
                });
              }}
            />
            <SelectField label="Sprint" value={filters.sprint ?? ""} options={sprintOptions} onChange={(value) => setFilters((prev) => ({ ...prev, sprint: value || undefined }))} />
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
              backgroundColor: uploadLoading ? "#89cfa4" : "var(--brand)",
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
          <h3 style={{ margin: 0, fontSize: 16 }}>Estimated Spend by Model</h3>
          <div style={{ height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={byModel}>
                <CartesianGrid strokeDasharray="3 3" stroke="#dfe7e2" />
                <XAxis dataKey="value" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="estimated_spend" fill="#1db954" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </article>
        <article className="panel" style={{ padding: 14, minHeight: 280 }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>{trend.title}</h3>
          <div style={{ height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={lineData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#dfe7e2" />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Line type="monotone" dataKey="estimated_spend" stroke="#119542" strokeWidth={2} dot={{ r: 2 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </article>
      </section>

      <section className="table-grid">
        <article className="panel" style={{ padding: 14 }}>
          <h3 style={{ margin: "0 0 10px", fontSize: 16 }}>Project Comparison</h3>
          <div style={{ overflow: "auto", maxHeight: 320 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ backgroundColor: "var(--surface-muted)" }}>
                  <th style={{ textAlign: "left", padding: 8 }}>Project</th>
                  <th style={{ textAlign: "right", padding: 8 }}>Spend</th>
                  <th style={{ textAlign: "right", padding: 8 }}>Perf</th>
                  <th style={{ textAlign: "right", padding: 8 }}>Cost/Perf</th>
                </tr>
              </thead>
              <tbody>
                {byProject.slice(0, 12).map((item) => (
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

        <article className="panel" style={{ padding: 14 }}>
          <h3 style={{ margin: "0 0 8px", fontSize: 16 }}>AI Panel</h3>
          <label style={{ display: "grid", gap: 6, marginBottom: 10 }}>
            <span style={{ fontSize: 12, color: "var(--text-muted)", fontWeight: 700 }}>Natural Language Question</span>
            <textarea
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              rows={3}
              style={{ resize: "vertical", border: "1px solid var(--border)", borderRadius: 8, padding: 8 }}
            />
          </label>
          {aiState.error && <div style={{ color: "var(--danger)", fontSize: 12, marginBottom: 8 }}>{aiState.error}</div>}
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>
            {aiState.model ? `AI model: ${aiState.model}` : "Run AI Analysis to generate insights"}
          </div>
          <div style={{ display: "grid", gap: 8, maxHeight: 250, overflow: "auto" }}>
            {[...aiState.insights, ...aiState.recommendations, ...aiState.queryResults, ...aiState.categories].slice(0, 8).map((item, index) => (
              <div key={index} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 8, fontSize: 12 }}>
                {extractMessage(item)}
              </div>
            ))}
          </div>
        </article>
      </section>
    </main>
  );
}
