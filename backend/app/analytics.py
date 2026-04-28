from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
COMMITS_PATH = ROOT_DIR / "mock_commits.json"
PRICING_PATH = ROOT_DIR / "backend" / "config" / "pricing.json"

WEIGHTS = {
    "longevity": 0.35,
    "bugfix": 0.30,
    "lead_time": 0.20,
    "iterations": 0.15,
}


def _parse_date(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _normalize(values: list[float], higher_is_better: bool = True) -> list[float]:
    low = min(values)
    high = max(values)
    if high == low:
        return [100.0 for _ in values]

    if higher_is_better:
        return [((value - low) / (high - low)) * 100.0 for value in values]
    return [((high - value) / (high - low)) * 100.0 for value in values]


def _estimate_tokens(revisions: int, comments: int, overrides: int, bug_fixes: int) -> tuple[int, int]:
    input_tokens = int(700 + (revisions * 180) + (comments * 50) + (overrides * 60))
    output_tokens = int(280 + (revisions * 75) + (bug_fixes * 120))
    return max(input_tokens, 1), max(output_tokens, 1)


def _sprint_sort_key(value: str) -> int:
    try:
        return int(value.split(" ", 1)[1])
    except Exception:
        return 0


def load_enriched_commits() -> list[dict[str, Any]]:
    raw_payload = _load_json(COMMITS_PATH)
    raw_commits = raw_payload.get("commits", raw_payload)
    pricing = _load_json(PRICING_PATH)
    default_pricing = pricing.get("_default", {"input_per_million": 1.0, "output_per_million": 2.0})

    commits: list[dict[str, Any]] = []
    commit_date_by_hash: dict[str, datetime] = {}
    for commit_hash, item in raw_commits.items():
        commit_date_by_hash[commit_hash] = _parse_date(item["commitDate"])

    if not commit_date_by_hash:
        return commits

    horizon = max(commit_date_by_hash.values()) + timedelta(days=60)

    for commit_hash, item in raw_commits.items():
        commit_date = _parse_date(item["commitDate"])
        merge_date = _parse_date(item["mergeDate"])
        lead_time_hours = max((merge_date - commit_date).total_seconds() / 3600.0, 1.0)

        overrides = item.get("overriddenByCommits", [])
        override_dates = [
            commit_date_by_hash[override_hash]
            for override_hash in overrides
            if override_hash in commit_date_by_hash and commit_date_by_hash[override_hash] > commit_date
        ]
        if override_dates:
            longevity_days = max((min(override_dates) - commit_date).total_seconds() / 86400.0, 0.0)
        else:
            longevity_days = max((horizon - commit_date).total_seconds() / 86400.0, 0.0)

        revisions = int(item.get("revisionsBeforeMerge", 0))
        comments = int(item.get("commentsBeforeMerge", 0))
        bug_fixes = int(item.get("bugFixOverridesCount", 0))
        iterations_raw = revisions + (comments / 4.0)

        input_tokens, output_tokens = _estimate_tokens(revisions, comments, len(overrides), bug_fixes)
        model = item.get("model", "unknown")
        model_pricing = pricing.get(model, default_pricing)
        estimated_cost = (
            (input_tokens / 1_000_000.0) * float(model_pricing["input_per_million"])
            + (output_tokens / 1_000_000.0) * float(model_pricing["output_per_million"])
        )

        commits.append(
            {
                "hash": commit_hash,
                "author": item.get("author"),
                "seniority": item.get("authorSeniority"),
                "team": item.get("team"),
                "project": item.get("project"),
                "model": model,
                "quarter": item.get("quarter"),
                "sprint": item.get("sprint"),
                "commit_date": commit_date.astimezone(timezone.utc).isoformat(),
                "merge_date": merge_date.astimezone(timezone.utc).isoformat(),
                "lead_time_hours": lead_time_hours,
                "longevity_days": longevity_days,
                "bug_fix_count": bug_fixes,
                "revisions": revisions,
                "comments": comments,
                "iterations_raw": iterations_raw,
                "overrides_count": len(overrides),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "estimated_cost": estimated_cost,
            }
        )

    longevity_scores = _normalize([item["longevity_days"] for item in commits], higher_is_better=True)
    bug_fix_scores = _normalize([item["bug_fix_count"] for item in commits], higher_is_better=False)
    lead_scores = _normalize([item["lead_time_hours"] for item in commits], higher_is_better=False)
    iteration_scores = _normalize([item["iterations_raw"] for item in commits], higher_is_better=False)

    for index, item in enumerate(commits):
        performance_score = (
            WEIGHTS["longevity"] * longevity_scores[index]
            + WEIGHTS["bugfix"] * bug_fix_scores[index]
            + WEIGHTS["lead_time"] * lead_scores[index]
            + WEIGHTS["iterations"] * iteration_scores[index]
        )
        item["longevity_score"] = round(longevity_scores[index], 2)
        item["bug_fix_score"] = round(bug_fix_scores[index], 2)
        item["lead_time_score"] = round(lead_scores[index], 2)
        item["iterations_score"] = round(iteration_scores[index], 2)
        item["performance_score"] = round(performance_score, 2)
        item["cost_performance_point"] = round(item["estimated_cost"] / max(performance_score, 1.0), 6)
        item["roi_score"] = round(performance_score / max(item["estimated_cost"], 0.000001), 2)

    return commits


def apply_filters(
    rows: list[dict[str, Any]],
    *,
    team: list[str] | None = None,
    project: list[str] | None = None,
    model: list[str] | None = None,
    seniority: list[str] | None = None,
    quarter: str | None = None,
    sprint: str | None = None,
) -> list[dict[str, Any]]:
    result = rows
    if team:
        allowed = set(team)
        result = [row for row in result if row.get("team") in allowed]
    if project:
        allowed = set(project)
        result = [row for row in result if row.get("project") in allowed]
    if model:
        allowed = set(model)
        result = [row for row in result if row.get("model") in allowed]
    if seniority:
        allowed = set(seniority)
        result = [row for row in result if row.get("seniority") in allowed]
    if quarter:
        result = [row for row in result if row.get("quarter") == quarter]
    if sprint:
        result = [row for row in result if row.get("sprint") == sprint]
    return result


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "total_commits": 0,
            "total_spend": 0.0,
            "avg_cost_per_commit": 0.0,
            "avg_performance_score": 0.0,
            "avg_lead_time_hours": 0.0,
            "avg_bug_fix_count": 0.0,
            "cost_per_performance_point": 0.0,
            "best_model_by_roi": None,
        }

    total_commits = len(rows)
    total_spend = sum(item["estimated_cost"] for item in rows)
    avg_performance = sum(item["performance_score"] for item in rows) / total_commits
    avg_lead_time = sum(item["lead_time_hours"] for item in rows) / total_commits
    avg_bug_fix = sum(item["bug_fix_count"] for item in rows) / total_commits

    by_model: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        by_model.setdefault(item["model"], []).append(item)

    best_model = None
    best_value = float("-inf")
    for model_name, group in by_model.items():
        group_spend = sum(entry["estimated_cost"] for entry in group)
        group_perf = sum(entry["performance_score"] for entry in group)
        value = group_perf / max(group_spend, 0.000001)
        if value > best_value:
            best_value = value
            best_model = model_name

    return {
        "total_commits": total_commits,
        "total_spend": round(total_spend, 4),
        "avg_cost_per_commit": round(total_spend / total_commits, 6),
        "avg_performance_score": round(avg_performance, 2),
        "avg_lead_time_hours": round(avg_lead_time, 2),
        "avg_bug_fix_count": round(avg_bug_fix, 2),
        "cost_per_performance_point": round(total_spend / max(sum(item["performance_score"] for item in rows), 1.0), 6),
        "best_model_by_roi": best_model,
    }


def breakdown(rows: list[dict[str, Any]], dimension: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        key = str(item.get(dimension, "Unknown"))
        groups.setdefault(key, []).append(item)

    total_commits = len(rows) or 1
    response: list[dict[str, Any]] = []
    for group_name, group_rows in groups.items():
        commits = len(group_rows)
        spend = sum(item["estimated_cost"] for item in group_rows)
        performance = sum(item["performance_score"] for item in group_rows)
        longevity_score = sum(item["longevity_score"] for item in group_rows) / commits
        bug_fix_score = sum(item["bug_fix_score"] for item in group_rows) / commits
        lead_time_score = sum(item["lead_time_score"] for item in group_rows) / commits
        iterations_score = sum(item["iterations_score"] for item in group_rows) / commits
        roi_score = performance / max(spend, 0.000001)
        response.append(
            {
                "dimension": dimension,
                "value": group_name,
                "commits": commits,
                "usage_pct": round((commits / total_commits) * 100.0, 2),
                "estimated_spend": round(spend, 4),
                "avg_performance_score": round(performance / commits, 2),
                "avg_longevity_score": round(longevity_score, 2),
                "avg_bug_fix_score": round(bug_fix_score, 2),
                "avg_lead_time_score": round(lead_time_score, 2),
                "avg_iterations_score": round(iterations_score, 2),
                "roi_score": round(roi_score, 2),
                "avg_lead_time_hours": round(sum(item["lead_time_hours"] for item in group_rows) / commits, 2),
                "avg_cost_per_commit": round(spend / commits, 6),
                "cost_per_performance_point": round(spend / max(performance, 1.0), 6),
            }
        )

    if dimension in {"quarter", "sprint"}:
        response.sort(key=lambda item: item["value"])
    else:
        response.sort(key=lambda item: item["estimated_spend"], reverse=True)
    return response


def spend_trend(rows: list[dict[str, Any]], *, quarter: str | None = None, sprint: str | None = None) -> dict[str, Any]:
    if sprint:
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in rows:
            day_label = datetime.fromisoformat(item["commit_date"]).strftime("%Y-%m-%d")
            groups.setdefault(day_label, []).append(item)

        points: list[dict[str, Any]] = []
        for label, group_rows in groups.items():
            spend = sum(entry["estimated_cost"] for entry in group_rows)
            points.append(
                {
                    "label": label,
                    "estimated_spend": round(spend, 4),
                    "commits": len(group_rows),
                    "avg_performance_score": round(sum(entry["performance_score"] for entry in group_rows) / len(group_rows), 2),
                }
            )
        points.sort(key=lambda item: item["label"])
        return {
            "mode": "sprint_daily",
            "title": f"Sprint Trend ({sprint})",
            "points": points,
        }

    if quarter:
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in rows:
            groups.setdefault(item["sprint"], []).append(item)

        points = []
        for label, group_rows in groups.items():
            spend = sum(entry["estimated_cost"] for entry in group_rows)
            points.append(
                {
                    "label": label,
                    "estimated_spend": round(spend, 4),
                    "commits": len(group_rows),
                    "avg_performance_score": round(sum(entry["performance_score"] for entry in group_rows) / len(group_rows), 2),
                }
            )
        points.sort(key=lambda item: _sprint_sort_key(item["label"]))
        return {
            "mode": "quarter_sprints",
            "title": f"Sprint Spend Trend ({quarter})",
            "points": points,
        }

    groups: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        groups.setdefault(item["quarter"], []).append(item)

    points = []
    for label, group_rows in groups.items():
        spend = sum(entry["estimated_cost"] for entry in group_rows)
        points.append(
            {
                "label": label,
                "estimated_spend": round(spend, 4),
                "commits": len(group_rows),
                "avg_performance_score": round(sum(entry["performance_score"] for entry in group_rows) / len(group_rows), 2),
            }
        )
    points.sort(key=lambda item: item["label"])
    return {
        "mode": "quarterly",
        "title": "Quarterly Spend Trend",
        "points": points,
    }


def options(rows: list[dict[str, Any]]) -> dict[str, Any]:
    team_projects: dict[str, set[str]] = {}
    quarter_sprints: dict[str, set[str]] = {}
    for item in rows:
        team = item.get("team")
        project = item.get("project")
        quarter = item.get("quarter")
        sprint = item.get("sprint")
        if team and project:
            team_projects.setdefault(team, set()).add(project)
        if quarter and sprint:
            quarter_sprints.setdefault(quarter, set()).add(sprint)

    return {
        "teams": sorted({item["team"] for item in rows if item.get("team")}),
        "projects": sorted({item["project"] for item in rows if item.get("project")}),
        "models": sorted({item["model"] for item in rows if item.get("model")}),
        "seniority_levels": sorted({item["seniority"] for item in rows if item.get("seniority")}),
        "quarters": sorted({item["quarter"] for item in rows if item.get("quarter")}),
        "sprints": sorted({item["sprint"] for item in rows if item.get("sprint")}, key=_sprint_sort_key),
        "team_projects": {team: sorted(list(projects)) for team, projects in team_projects.items()},
        "quarter_sprints": {
            quarter_key: sorted(list(sprints), key=_sprint_sort_key) for quarter_key, sprints in quarter_sprints.items()
        },
    }
