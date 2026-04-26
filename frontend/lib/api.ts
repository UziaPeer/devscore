import type { AIItem, BreakdownItem, DataSourceInfo, Filters, OptionsPayload, Summary, TrendPayload } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

function buildQuery(filters: Filters): string {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (!value) {
      return;
    }
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (item) {
          params.append(key, item);
        }
      });
    } else {
      params.set(key, value);
    }
  });
  return params.toString();
}

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function getSummary(filters: Filters): Promise<Summary> {
  const query = buildQuery(filters);
  return fetchJson<Summary>(`/analytics/summary${query ? `?${query}` : ""}`);
}

export async function getBreakdown(dimension: string, filters: Filters): Promise<BreakdownItem[]> {
  const query = buildQuery(filters);
  const suffix = query ? `&${query}` : "";
  return fetchJson<BreakdownItem[]>(`/analytics/breakdown?dimension=${dimension}${suffix}`);
}

export async function getTrend(filters: Filters): Promise<TrendPayload> {
  const query = buildQuery(filters);
  return fetchJson<TrendPayload>(`/analytics/trend${query ? `?${query}` : ""}`);
}

export async function getOptions(): Promise<OptionsPayload> {
  return fetchJson<OptionsPayload>("/analytics/options");
}

export async function postAI(path: string, filters: Filters & { question?: string }): Promise<{ items: AIItem[]; model: string }> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(filters)
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `AI request failed with ${response.status}`);
  }
  return (await response.json()) as { items: AIItem[]; model: string };
}

export async function getDataSource(): Promise<DataSourceInfo> {
  return fetchJson<DataSourceInfo>("/data/source");
}

export async function uploadDataSource(file: File): Promise<DataSourceInfo> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(`${API_BASE}/data/upload`, {
    method: "POST",
    body: formData
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Upload failed with ${response.status}`);
  }
  return (await response.json()) as DataSourceInfo;
}
