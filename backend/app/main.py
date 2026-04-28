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
    quarter: str | None = None
    sprint: str | None = None


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

    if "subscriptions" in payload:
        subscriptions = payload["subscriptions"]
        if not isinstance(subscriptions, dict):
            raise HTTPException(status_code=400, detail="subscriptions must be an object when provided.")
        for author_name, models in subscriptions.items():
            if not isinstance(author_name, str) or not author_name.strip():
                raise HTTPException(status_code=400, detail="Each subscriptions key must be an author string.")
            if not isinstance(models, list) or not all(isinstance(model_name, str) for model_name in models):
                raise HTTPException(
                    status_code=400,
                    detail=f"subscriptions for author '{author_name}' must be an array of model strings.",
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
    team: list[str] | None = Query(default=None),
    project: list[str] | None = Query(default=None),
    model: list[str] | None = Query(default=None),
    seniority: list[str] | None = Query(default=None),
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


@app.get("/analytics/trend")
def analytics_trend(
    team: list[str] | None = Query(default=None),
    project: list[str] | None = Query(default=None),
    model: list[str] | None = Query(default=None),
    seniority: list[str] | None = Query(default=None),
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
