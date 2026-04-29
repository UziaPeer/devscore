from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from .analytics import COMMITS_PATH, apply_filters, breakdown, load_enriched_commits, options, spend_trend, summarize

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / "backend" / ".env")


class FilterPayload(BaseModel):
    team: list[str] | None = None
    project: list[str] | None = None
    model: list[str] | None = None
    seniority: list[str] | None = None
    quarter: list[str] | None = None
    sprint: list[str] | None = None


class QueryPayload(FilterPayload):
    question: str = Field(min_length=5, max_length=800)


class AIResponse(BaseModel):
    items: list[dict[str, Any]]
    model: str


class DataSourceResponse(BaseModel):
    filename: str
    records: int
    size_bytes: int
    updated_at: str


class QuickAIPayload(BaseModel):
    summary: dict[str, Any]
    by_model: list[dict[str, Any]]
    by_project: list[dict[str, Any]]
    trend_points: list[dict[str, Any]]
    question: str | None = None


class QuickAIResponse(BaseModel):
    insights: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    query_results: list[dict[str, Any]]
    categories: list[dict[str, Any]]
    roi_highlights: list[dict[str, Any]]
    model: str


app = FastAPI(
    title="DevScore API",
    description="AI cost and PR outcome analytics.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def _all_rows() -> list[dict[str, Any]]:
    return load_enriched_commits()


def _filtered_rows(filters: FilterPayload) -> list[dict[str, Any]]:
    return apply_filters(
        _all_rows(),
        team=filters.team,
        project=filters.project,
        model=filters.model,
        seniority=filters.seniority,
        quarter=filters.quarter,
        sprint=filters.sprint,
    )


def _require_openai() -> tuple[Any, str]:
    if OpenAI is None:
        raise HTTPException(status_code=500, detail="OpenAI SDK is not installed.")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is required for AI endpoints.")
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    return OpenAI(api_key=api_key), model


def _run_ai_json(prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
    client, model = _require_openai()
    try:
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": [{"type": "input_text", "text": prompt}]},
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": json.dumps(payload, ensure_ascii=True)}],
                },
            ],
            text={"format": {"type": "json_object"}},
        )
        output_text = response.output_text
        output = json.loads(output_text)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=502, detail=f"AI request failed: {exc}") from exc

    if not isinstance(output, dict):
        raise HTTPException(status_code=502, detail="AI response format was invalid.")
    output["model"] = model
    return output


def _validate_dataset_shape(payload: Any) -> dict[str, Any]:
    required_keys = {
        "author",
        "authorSeniority",
        "team",
        "project",
        "model",
        "commitDate",
        "mergeDate",
        "overriddenByCommits",
        "bugFixOverridesCount",
        "revisionsBeforeMerge",
        "commentsBeforeMerge",
        "sprint",
        "quarter",
    }
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(status_code=400, detail="Uploaded file must be a non-empty JSON object.")

    commits_payload = payload.get("commits", payload)
    if not isinstance(commits_payload, dict) or not commits_payload:
        raise HTTPException(status_code=400, detail="Uploaded file must include a non-empty commits object.")

    for commit_hash, item in commits_payload.items():
        if not isinstance(commit_hash, str) or not commit_hash.strip():
            raise HTTPException(status_code=400, detail="Each top-level key must be a commit hash string.")
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"Commit '{commit_hash}' must be a JSON object.")
        missing = sorted(required_keys.difference(item.keys()))
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Commit '{commit_hash}' is missing required keys: {', '.join(missing)}",
            )
        if not isinstance(item.get("overriddenByCommits"), list):
            raise HTTPException(status_code=400, detail=f"Commit '{commit_hash}' has invalid overriddenByCommits.")
        if "lines" in item and not isinstance(item.get("lines"), int):
            raise HTTPException(status_code=400, detail=f"Commit '{commit_hash}' has invalid lines value.")
        if str(item.get("model", "")).strip().lower() == "human":
            raise HTTPException(
                status_code=400,
                detail="Uploaded dataset cannot contain 'Human' model commits. Human control data is fixed server-side.",
            )

    subscriptions_key = "subscriptions" if "subscriptions" in payload else "subscription" if "subscription" in payload else None
    if subscriptions_key:
        subscriptions = payload[subscriptions_key]
        if not isinstance(subscriptions, dict):
            raise HTTPException(status_code=400, detail=f"{subscriptions_key} must be an object when provided.")
        for author_name, models in subscriptions.items():
            if not isinstance(author_name, str) or not author_name.strip():
                raise HTTPException(status_code=400, detail=f"Each {subscriptions_key} key must be an author string.")
            if not isinstance(models, list) or not all(isinstance(model_name, str) for model_name in models):
                raise HTTPException(
                    status_code=400,
                    detail=f"{subscriptions_key} for author '{author_name}' must be an array of model strings.",
                )

    return payload


def _data_source_response() -> DataSourceResponse:
    stat = COMMITS_PATH.stat()
    return DataSourceResponse(
        filename=COMMITS_PATH.name,
        records=len(_all_rows()),
        size_bytes=stat.st_size,
        updated_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/data/source", response_model=DataSourceResponse)
def data_source() -> DataSourceResponse:
    return _data_source_response()


@app.post("/data/upload", response_model=DataSourceResponse)
async def data_upload(file: UploadFile = File(...)) -> DataSourceResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file has no name.")
    if not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON files are supported.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        payload = json.loads(content.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UTF-8 file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    validated = _validate_dataset_shape(payload)

    try:
        # Uploads are intentionally scoped to mock_commits.json only.
        # The human control-group dataset (mock_commits_human_control.json) is fixed and not user-replaceable.
        with COMMITS_PATH.open("w", encoding="utf-8") as handle:
            json.dump(validated, handle, indent=2)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to store uploaded dataset: {exc}") from exc

    _all_rows.cache_clear()
    return _data_source_response()


@app.get("/analytics/options")
def analytics_options() -> dict[str, Any]:
    return options(_all_rows())


@app.get("/analytics/summary")
def analytics_summary(
    team: list[str] | None = Query(default=None),
    project: list[str] | None = Query(default=None),
    model: list[str] | None = Query(default=None),
    seniority: list[str] | None = Query(default=None),
    quarter: list[str] | None = Query(default=None),
    sprint: list[str] | None = Query(default=None),
) -> dict[str, Any]:
    rows = _filtered_rows(
        FilterPayload(
            team=team,
            project=project,
            model=model,
            seniority=seniority,
            quarter=quarter,
            sprint=sprint,
        )
    )
    return summarize(rows)


@app.get("/analytics/breakdown")
def analytics_breakdown(
    dimension: Literal["team", "project", "model", "quarter", "sprint", "seniority"] = Query(default="model"),
    team: list[str] | None = Query(default=None),
    project: list[str] | None = Query(default=None),
    model: list[str] | None = Query(default=None),
    seniority: list[str] | None = Query(default=None),
    quarter: list[str] | None = Query(default=None),
    sprint: list[str] | None = Query(default=None),
) -> list[dict[str, Any]]:
    rows = _filtered_rows(
        FilterPayload(
            team=team,
            project=project,
            model=model,
            seniority=seniority,
            quarter=quarter,
            sprint=sprint,
        )
    )
    return breakdown(rows, dimension)


@app.get("/analytics/trend")
def analytics_trend(
    team: list[str] | None = Query(default=None),
    project: list[str] | None = Query(default=None),
    model: list[str] | None = Query(default=None),
    seniority: list[str] | None = Query(default=None),
    quarter: list[str] | None = Query(default=None),
    sprint: list[str] | None = Query(default=None),
) -> dict[str, Any]:
    rows = _filtered_rows(
        FilterPayload(
            team=team,
            project=project,
            model=model,
            seniority=seniority,
            quarter=quarter,
            sprint=sprint,
        )
    )
    return spend_trend(rows, quarter=quarter, sprint=sprint)


@app.post("/ai/insights", response_model=AIResponse)
def ai_insights(filters: FilterPayload) -> AIResponse:
    rows = _filtered_rows(filters)
    context = {
        "summary": summarize(rows),
        "breakdown_model": breakdown(rows, "model"),
        "breakdown_project": breakdown(rows, "project"),
        "breakdown_team": breakdown(rows, "team"),
    }
    payload = _run_ai_json(
        prompt=(
            "You analyze AI engineering usage. Return JSON with key 'items'. "
            "Each item: title, finding, business_impact, confidence (0-1). "
            "Keep up to 5 items and be practical."
        ),
        payload=context,
    )
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise HTTPException(status_code=502, detail="AI output did not include 'items' list.")
    return AIResponse(items=items, model=payload["model"])


@app.post("/ai/recommendations", response_model=AIResponse)
def ai_recommendations(filters: FilterPayload) -> AIResponse:
    rows = _filtered_rows(filters)
    context = {
        "summary": summarize(rows),
        "by_model": breakdown(rows, "model"),
        "by_project": breakdown(rows, "project"),
        "by_team": breakdown(rows, "team"),
    }
    payload = _run_ai_json(
        prompt=(
            "You optimize AI costs for engineering teams. Return JSON with key 'items'. "
            "Each item: action, rationale, expected_savings_pct, risk_level, affected_scope."
        ),
        payload=context,
    )
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise HTTPException(status_code=502, detail="AI output did not include 'items' list.")
    return AIResponse(items=items, model=payload["model"])


@app.post("/ai/categorize", response_model=AIResponse)
def ai_categorize(filters: FilterPayload) -> AIResponse:
    rows = _filtered_rows(filters)[:80]
    row_by_hash = {row["hash"]: row for row in rows}
    context_rows = [
        {
            "hash": row["hash"],
            "team": row["team"],
            "project": row["project"],
            "model": row["model"],
            "lead_time_hours": row["lead_time_hours"],
            "bug_fix_count": row["bug_fix_count"],
            "iterations": row["iterations_raw"],
            "performance_score": row["performance_score"],
        }
        for row in rows
    ]
    payload = _run_ai_json(
        prompt=(
            "Classify commit usage quality. Return JSON with key 'items'. "
            "Each item: hash, category. Categories: high-value, review-heavy, bug-prone, fast-delivery."
        ),
        payload={"rows": context_rows},
    )


def _strip_cost_performance_point(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: _strip_cost_performance_point(value)
            for key, value in payload.items()
            if key != "cost_per_performance_point"
        }
    if isinstance(payload, list):
        return [_strip_cost_performance_point(item) for item in payload]
    return payload


def _build_category_summary_from_breakdown(by_model: list[dict[str, Any]]) -> list[dict[str, Any]]:
    categories = ("high-value", "review-heavy", "bug-prone", "fast-delivery")
    summary: list[dict[str, Any]] = []

    for row in by_model:
        model_name = str(row.get("value", "Unknown"))
        commits = int(row.get("commits", 0))
        if commits <= 0 or model_name.lower() == "human":
            continue

        avg_perf = float(row.get("avg_performance_score", 0.0))
        avg_bug = float(row.get("avg_bug_fix_count", 0.0))
        avg_iter = float(row.get("avg_iterations_raw", 0.0))
        avg_lead = float(row.get("avg_lead_time_hours", 0.0))

        weights = {
            "high-value": max(avg_perf, 0.0),
            "review-heavy": max(avg_iter, 0.0) * 18.0,
            "bug-prone": max(avg_bug, 0.0) * 30.0,
            "fast-delivery": max(120.0 - avg_lead, 0.0),
        }
        weight_sum = sum(weights.values()) or 1.0

        distribution: list[dict[str, Any]] = []
        allocated = 0
        for index, category_name in enumerate(categories):
            percentage = (weights[category_name] / weight_sum) * 100.0
            if index < len(categories) - 1:
                category_commits = int(round((commits * percentage) / 100.0))
                allocated += category_commits
            else:
                category_commits = max(commits - allocated, 0)
            distribution.append(
                {
                    "category": category_name,
                    "commits": category_commits,
                    "percentage": round((category_commits / commits) * 100.0 if commits else 0.0, 2),
                }
            )

        summary.append(
            {
                "model": model_name,
                "total_commits": commits,
                "breakdown": distribution,
            }
        )
    return summary


def _build_roi_highlights_from_breakdown(by_model: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in by_model:
        model_name = str(row.get("value", "Unknown"))
        if model_name.strip().lower() == "human":
            continue
        hours_saved = float(row.get("estimated_hours_saved", 0.0))
        value_saved = float(row.get("estimated_value_saved", 0.0))
        spend = float(row.get("estimated_spend", 0.0))
        roi_score = float(row.get("roi_score", 0.0))
        if spend <= 0 or hours_saved <= 0 or value_saved <= 0:
            continue
        candidates.append(
            {
                "model": model_name,
                "hours_saved": hours_saved,
                "value_saved": value_saved,
                "spend": spend,
                "roi_score": roi_score,
            }
        )

    candidates.sort(key=lambda item: item["roi_score"], reverse=True)
    highlights: list[dict[str, Any]] = []
    for item in candidates[:3]:
        sentence = (
            f'{item["model"]} saved an estimated {item["hours_saved"]:.0f} engineering hours, '
            f'worth ${item["value_saved"]:,.0f}, at a cost of ${item["spend"]:,.0f}. '
            f'ROI: {item["roi_score"]:.1f}x.'
        )
        highlights.append(
            {
                "title": f'{item["model"]} ROI Highlight',
                "finding": sentence,
                "model": item["model"],
                "hours_saved": round(item["hours_saved"], 2),
                "value_saved": round(item["value_saved"], 2),
                "spend": round(item["spend"], 4),
                "roi_score": round(item["roi_score"], 2),
            }
        )
    return highlights
    raw_items = payload.get("items", [])
    if not isinstance(raw_items, list):
        raise HTTPException(status_code=502, detail="AI output did not include 'items' list.")

    allowed_categories = ("high-value", "review-heavy", "bug-prone", "fast-delivery")
    by_model_counts: dict[str, dict[str, int]] = {}
    by_model_total: dict[str, int] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        item_hash = item.get("hash")
        category = item.get("category")
        if not isinstance(item_hash, str) or not isinstance(category, str):
            continue
        row = row_by_hash.get(item_hash)
        if row is None:
            continue
        normalized_category = category.strip().lower()
        if normalized_category not in allowed_categories:
            continue
        model_name = str(row.get("model", "Unknown"))
        model_counts = by_model_counts.setdefault(model_name, {name: 0 for name in allowed_categories})
        model_counts[normalized_category] += 1
        by_model_total[model_name] = by_model_total.get(model_name, 0) + 1

    summary_items: list[dict[str, Any]] = []
    for model_name in sorted(by_model_counts.keys()):
        total = max(by_model_total.get(model_name, 0), 1)
        breakdown = []
        for category_name in allowed_categories:
            count = by_model_counts[model_name].get(category_name, 0)
            pct = round((count / total) * 100.0, 2)
            breakdown.append(
                {
                    "category": category_name,
                    "commits": count,
                    "percentage": pct,
                }
            )
        summary_items.append(
            {
                "model": model_name,
                "total_commits": by_model_total.get(model_name, 0),
                "breakdown": breakdown,
            }
        )

    return AIResponse(items=summary_items, model=payload["model"])


@app.post("/ai/query", response_model=AIResponse)
def ai_query(payload: QueryPayload) -> AIResponse:
    rows = _filtered_rows(payload)
    context = {
        "question": payload.question,
        "summary": summarize(rows),
        "by_model": breakdown(rows, "model"),
        "by_project": breakdown(rows, "project"),
        "by_team": breakdown(rows, "team"),
        "by_quarter": breakdown(rows, "quarter"),
    }
    output = _run_ai_json(
        prompt=(
            "Answer the user question with data-backed insights. Return JSON with key 'items'. "
            "Each item: answer, supporting_data, confidence (0-1). Provide 1-3 items."
        ),
        payload=context,
    )
    items = output.get("items", [])
    if not isinstance(items, list):
        raise HTTPException(status_code=502, detail="AI output did not include 'items' list.")
    return AIResponse(items=items, model=output["model"])


@app.post("/ai/quick", response_model=QuickAIResponse)
def ai_quick(payload: QuickAIPayload) -> QuickAIResponse:
    cleaned_payload = _strip_cost_performance_point(payload.model_dump())
    by_model = cleaned_payload.get("by_model", [])
    categories = _build_category_summary_from_breakdown(by_model if isinstance(by_model, list) else [])
    roi_highlights = _build_roi_highlights_from_breakdown(by_model if isinstance(by_model, list) else [])

    ai_output = _run_ai_json(
        prompt=(
            "You are an engineering analytics assistant. Use only the provided dashboard snapshot. "
            "Do not use cost_per_performance_point at all. "
            "Return compact JSON with keys: insights, recommendations, query_results. "
            "insights: up to 5 items with title, finding, confidence. "
            "recommendations: up to 5 items with action, rationale, risk_level. "
            "query_results: up to 3 items with answer, supporting_data, confidence."
        ),
        payload=cleaned_payload,
    )

    insights = ai_output.get("insights", [])
    recommendations = ai_output.get("recommendations", [])
    query_results = ai_output.get("query_results", [])

    if not isinstance(insights, list) or not isinstance(recommendations, list) or not isinstance(query_results, list):
        raise HTTPException(status_code=502, detail="AI quick output format was invalid.")

    return QuickAIResponse(
        insights=insights,
        recommendations=recommendations,
        query_results=query_results,
        categories=categories,
        roi_highlights=roi_highlights,
        model=ai_output["model"],
    )
