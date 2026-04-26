from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .analytics import apply_filters, breakdown, load_enriched_commits, options, summarize

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


class FilterPayload(BaseModel):
    team: str | None = None
    project: str | None = None
    model: str | None = None
    seniority: str | None = None
    quarter: str | None = None
    sprint: str | None = None


class QueryPayload(FilterPayload):
    question: str = Field(min_length=5, max_length=800)


class AIResponse(BaseModel):
    items: list[dict[str, Any]]
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/analytics/options")
def analytics_options() -> dict[str, list[str]]:
    return options(_all_rows())


@app.get("/analytics/summary")
def analytics_summary(
    team: str | None = None,
    project: str | None = None,
    model: str | None = None,
    seniority: str | None = None,
    quarter: str | None = None,
    sprint: str | None = None,
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
    team: str | None = None,
    project: str | None = None,
    model: str | None = None,
    seniority: str | None = None,
    quarter: str | None = None,
    sprint: str | None = None,
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
            "Each item: hash, category, reason. Categories: high-value, review-heavy, bug-prone, fast-delivery."
        ),
        payload={"rows": context_rows},
    )
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise HTTPException(status_code=502, detail="AI output did not include 'items' list.")
    return AIResponse(items=items, model=payload["model"])


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
