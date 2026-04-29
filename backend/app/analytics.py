from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
COMMITS_PATH = ROOT_DIR / "mock_commits.json"
HUMAN_CONTROL_COMMITS_PATH = ROOT_DIR / "mock_commits_human_control.json"
PRICING_PATH = ROOT_DIR / "backend" / "config" / "pricing.json"

WEIGHTS = {
    "longevity": 0.35,
    "bugfix": 0.30,
    "lead_time": 0.20,
    "iterations": 0.15,
}

HOURLY_RATE_BY_SENIORITY = {
    "Junior": 35.0,
    "2": 50.0,
    "3": 70.0,
    "4": 90.0,
    "Senior": 120.0,
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


def _estimate_tokens_from_lines(lines: int) -> int:
    # Product rule: 1 line ~= 15 tokens on average.
    return max(lines * 15, 1)


def _normalize_model_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.strip().lower())


def _sprint_sort_key(value: str) -> int:
    try:
        return int(value.split(" ", 1)[1])
    except Exception:
        return 0


def _seniority_sort_key(value: str) -> tuple[int, str]:
    normalized = value.strip().lower()
    order = {
        "junior": 1,
        "2": 2,
        "3": 3,
        "4": 4,
        "senior": 5,
    }
    return (order.get(normalized, 999), normalized)


def _estimated_friction_hours(item: dict[str, Any]) -> float:
    short_lived_penalty = min(max(0.0, 14.0 - float(item.get("longevity_days", 0.0))) * 0.02, 0.25)
    return (
        float(item.get("lead_time_hours", 0.0)) * 0.005
        + int(item.get("revisions", 0)) * 0.20
        + int(item.get("comments", 0)) * 0.025
        + int(item.get("bug_fix_count", 0)) * 0.40
        + short_lived_penalty
    )


def load_enriched_commits() -> list[dict[str, Any]]:
    raw_payload = _load_json(COMMITS_PATH)
    control_payload = _load_json(HUMAN_CONTROL_COMMITS_PATH) if HUMAN_CONTROL_COMMITS_PATH.exists() else {}

    primary_commits = raw_payload.get("commits", raw_payload)
    control_commits = control_payload.get("commits", control_payload) if control_payload else {}
    raw_commits = {**primary_commits, **control_commits}

    primary_subscriptions = raw_payload.get("subscriptions", raw_payload.get("subscription", {}))
    control_subscriptions = control_payload.get("subscriptions", control_payload.get("subscription", {})) if control_payload else {}
    pricing = _load_json(PRICING_PATH)
    default_pricing = pricing.get("_default", {"cost_per_million": 3.0, "subscription_cost": 60.0})
    pricing_model_keys = {
        _normalize_model_key(model_name): model_name for model_name in pricing.keys() if model_name != "_default"
    }

    subscriptions_by_author: dict[str, set[str]] = {}
    for source_subscriptions in (primary_subscriptions, control_subscriptions):
        if not isinstance(source_subscriptions, dict):
            continue
        for author_name, model_names in source_subscriptions.items():
            if not isinstance(model_names, list):
                continue
            normalized_models = subscriptions_by_author.setdefault(author_name, set())
            for model_name in model_names:
                if not isinstance(model_name, str):
                    continue
                normalized = _normalize_model_key(model_name)
                normalized_models.add(pricing_model_keys.get(normalized, model_name))

    commits: list[dict[str, Any]] = []
    subscribed_usage_counts: dict[tuple[str, str], int] = {}
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

        model_raw = str(item.get("model", "unknown"))
        model = pricing_model_keys.get(_normalize_model_key(model_raw), model_raw)
        author = str(item.get("author", "Unknown"))
        lines = int(item.get("lines", 100))
        token_estimate = _estimate_tokens_from_lines(max(lines, 1))
        is_subscribed = model in subscriptions_by_author.get(author, set())
        if is_subscribed:
            subscribed_usage_counts[(author, model)] = subscribed_usage_counts.get((author, model), 0) + 1

        commits.append(
            {
                "hash": commit_hash,
                "author": author,
                "seniority": item.get("authorSeniority"),
                "team": item.get("team"),
                "project": item.get("project"),
                "model": model,
                "lines": lines,
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
                "estimated_tokens": token_estimate,
                "is_subscribed_model": is_subscribed,
                "cost_mode": "subscription" if is_subscribed else "per_token",
                "estimated_cost": 0.0,
            }
        )

    for item in commits:
        model_pricing = pricing.get(item["model"], default_pricing)
        if item["is_subscribed_model"]:
            usage_count = max(subscribed_usage_counts.get((item["author"], item["model"]), 1), 1)
            estimated_cost = float(model_pricing["subscription_cost"]) / usage_count
        else:
            estimated_cost = (item["estimated_tokens"] / 1_000_000.0) * float(model_pricing["cost_per_million"])
        item["estimated_cost"] = estimated_cost

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

    human_rows = [item for item in commits if str(item.get("model", "")).strip().lower() == "human"]
    baseline_by_team_seniority: dict[tuple[str, str], list[float]] = {}
    baseline_by_seniority: dict[str, list[float]] = {}

    for item in human_rows:
        friction_hours = _estimated_friction_hours(item)
        seniority = str(item.get("seniority", ""))
        team = str(item.get("team", ""))
        baseline_by_team_seniority.setdefault((team, seniority), []).append(friction_hours)
        baseline_by_seniority.setdefault(seniority, []).append(friction_hours)

    global_baseline = (
        sum(_estimated_friction_hours(item) for item in human_rows) / len(human_rows)
        if human_rows
        else 0.0
    )

    def _average(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    for item in commits:
        model_name = str(item.get("model", "")).strip().lower()
        seniority = str(item.get("seniority", ""))
        team = str(item.get("team", ""))
        hourly_rate = float(HOURLY_RATE_BY_SENIORITY.get(seniority, 70.0))
        actual_friction_hours = _estimated_friction_hours(item)

        baseline_hours = _average(baseline_by_team_seniority.get((team, seniority), []))
        if baseline_hours <= 0:
            baseline_hours = _average(baseline_by_seniority.get(seniority, []))
        if baseline_hours <= 0:
            baseline_hours = global_baseline

        hours_saved = 0.0 if model_name == "human" else baseline_hours - actual_friction_hours
        value_saved = hours_saved * hourly_rate
        ai_cost = float(item.get("estimated_cost", 0.0))

        item["hourly_rate"] = round(hourly_rate, 2)
        item["estimated_friction_hours"] = round(actual_friction_hours, 2)
        item["human_baseline_friction_hours"] = round(baseline_hours, 2)
        item["estimated_hours_saved"] = round(hours_saved, 2)
        item["estimated_value_saved"] = round(value_saved, 2)
        item["roi_score"] = round(value_saved / max(ai_cost, 0.000001), 2) if model_name != "human" else 0.0
        item["cost_per_hour_saved"] = round(ai_cost / hours_saved, 4) if hours_saved > 0 else 0.0

    return commits


def apply_filters(
    rows: list[dict[str, Any]],
    *,
    team: list[str] | None = None,
    project: list[str] | None = None,
    model: list[str] | None = None,
    seniority: list[str] | None = None,
    quarter: list[str] | None = None,
    sprint: list[str] | None = None,
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
        allowed = set(quarter)
        result = [row for row in result if row.get("quarter") in allowed]
    if sprint:
        allowed = set(sprint)
        result = [row for row in result if row.get("sprint") in allowed]
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
            "estimated_hours_saved": 0.0,
            "estimated_value_saved": 0.0,
            "financial_roi": 0.0,
            "best_model_by_roi": None,
        }

    total_commits = len(rows)
    total_spend = sum(item["estimated_cost"] for item in rows)
    avg_performance = sum(item["performance_score"] for item in rows) / total_commits
    avg_lead_time = sum(item["lead_time_hours"] for item in rows) / total_commits
    avg_bug_fix = sum(item["bug_fix_count"] for item in rows) / total_commits
    total_hours_saved = sum(float(item.get("estimated_hours_saved", 0.0)) for item in rows)
    total_value_saved = sum(float(item.get("estimated_value_saved", 0.0)) for item in rows)

    by_model: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        by_model.setdefault(item["model"], []).append(item)

    best_model = None
    best_value = float("-inf")
    for model_name, group in by_model.items():
        if str(model_name).strip().lower() == "human":
            continue
        group_spend = sum(entry["estimated_cost"] for entry in group)
        group_value_saved = sum(float(entry.get("estimated_value_saved", 0.0)) for entry in group)
        value = group_value_saved / max(group_spend, 0.000001)
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
        "estimated_hours_saved": round(total_hours_saved, 2),
        "estimated_value_saved": round(total_value_saved, 2),
        "financial_roi": round(total_value_saved / max(total_spend, 0.000001), 2),
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
        api_spend = sum(item["estimated_cost"] for item in group_rows if item.get("cost_mode") == "per_token")
        subscription_spend = sum(item["estimated_cost"] for item in group_rows if item.get("cost_mode") == "subscription")
        total_tokens = sum(int(item.get("estimated_tokens", 0)) for item in group_rows)
        api_tokens = sum(int(item.get("estimated_tokens", 0)) for item in group_rows if item.get("cost_mode") == "per_token")
        subscription_tokens = sum(
            int(item.get("estimated_tokens", 0)) for item in group_rows if item.get("cost_mode") == "subscription"
        )
        performance = sum(item["performance_score"] for item in group_rows)
        avg_longevity_days = sum(item["longevity_days"] for item in group_rows) / commits
        avg_bug_fix_count = sum(item["bug_fix_count"] for item in group_rows) / commits
        avg_iterations_raw = sum(item["iterations_raw"] for item in group_rows) / commits
        longevity_score = sum(item["longevity_score"] for item in group_rows) / commits
        bug_fix_score = sum(item["bug_fix_score"] for item in group_rows) / commits
        lead_time_score = sum(item["lead_time_score"] for item in group_rows) / commits
        iterations_score = sum(item["iterations_score"] for item in group_rows) / commits
        hours_saved = sum(float(item.get("estimated_hours_saved", 0.0)) for item in group_rows)
        value_saved = sum(float(item.get("estimated_value_saved", 0.0)) for item in group_rows)
        roi_score = value_saved / max(spend, 0.000001) if spend > 0 else 0.0
        response.append(
            {
                "dimension": dimension,
                "value": group_name,
                "commits": commits,
                "usage_pct": round((commits / total_commits) * 100.0, 2),
                "estimated_spend": round(spend, 4),
                "api_spend": round(api_spend, 4),
                "api_spend_pct": round((api_spend / spend) * 100.0, 2) if spend > 0 else 0.0,
                "subscription_spend": round(subscription_spend, 4),
                "subscription_spend_pct": round((subscription_spend / spend) * 100.0, 2) if spend > 0 else 0.0,
                "estimated_tokens": total_tokens,
                "api_tokens": api_tokens,
                "api_tokens_pct": round((api_tokens / total_tokens) * 100.0, 2) if total_tokens > 0 else 0.0,
                "subscription_tokens": subscription_tokens,
                "subscription_tokens_pct": round((subscription_tokens / total_tokens) * 100.0, 2)
                if total_tokens > 0
                else 0.0,
                "avg_performance_score": round(performance / commits, 2),
                "avg_longevity_days": round(avg_longevity_days, 2),
                "avg_bug_fix_count": round(avg_bug_fix_count, 2),
                "avg_iterations_raw": round(avg_iterations_raw, 2),
                "avg_longevity_score": round(longevity_score, 2),
                "avg_bug_fix_score": round(bug_fix_score, 2),
                "avg_lead_time_score": round(lead_time_score, 2),
                "avg_iterations_score": round(iterations_score, 2),
                "roi_score": round(roi_score, 2),
                "avg_lead_time_hours": round(sum(item["lead_time_hours"] for item in group_rows) / commits, 2),
                "avg_cost_per_commit": round(spend / commits, 6),
                "cost_per_performance_point": round(spend / max(performance, 1.0), 6),
                "estimated_hours_saved": round(hours_saved, 2),
                "estimated_value_saved": round(value_saved, 2),
                "cost_per_hour_saved": round(spend / hours_saved, 4) if hours_saved > 0 else 0.0,
            }
        )

    human_row = next((row for row in response if row["value"] == "Human"), None) if dimension == "model" else None
    if human_row:
        for row in response:
            row["vs_human_performance_delta"] = round(row["avg_performance_score"] - human_row["avg_performance_score"], 2)
            row["vs_human_longevity_days_delta"] = round(row["avg_longevity_days"] - human_row["avg_longevity_days"], 2)
            row["vs_human_bug_fix_count_delta"] = round(row["avg_bug_fix_count"] - human_row["avg_bug_fix_count"], 2)
            row["vs_human_lead_time_hours_delta"] = round(row["avg_lead_time_hours"] - human_row["avg_lead_time_hours"], 2)
            row["vs_human_iterations_raw_delta"] = round(row["avg_iterations_raw"] - human_row["avg_iterations_raw"], 2)
            row["vs_human_roi_delta"] = round(row["roi_score"] - human_row["roi_score"], 2)
    elif dimension == "model":
        for row in response:
            row["vs_human_performance_delta"] = None
            row["vs_human_longevity_days_delta"] = None
            row["vs_human_bug_fix_count_delta"] = None
            row["vs_human_lead_time_hours_delta"] = None
            row["vs_human_iterations_raw_delta"] = None
            row["vs_human_roi_delta"] = None

    if dimension in {"quarter", "sprint"}:
        response.sort(key=lambda item: item["value"])
    else:
        response.sort(key=lambda item: item["estimated_spend"], reverse=True)
    return response


def spend_trend(
    rows: list[dict[str, Any]],
    *,
    quarter: list[str] | None = None,
    sprint: list[str] | None = None,
) -> dict[str, Any]:
    def _build_trend_point(label: str, group_rows: list[dict[str, Any]]) -> dict[str, Any]:
        spend = sum(entry["estimated_cost"] for entry in group_rows)
        api_spend = sum(entry["estimated_cost"] for entry in group_rows if entry.get("cost_mode") == "per_token")
        subscription_spend = sum(entry["estimated_cost"] for entry in group_rows if entry.get("cost_mode") == "subscription")
        return {
            "label": label,
            "estimated_spend": round(spend, 4),
            "commits": len(group_rows),
            "avg_performance_score": round(sum(entry["performance_score"] for entry in group_rows) / len(group_rows), 2),
            "api_spend": round(api_spend, 4),
            "api_spend_pct": round((api_spend / spend) * 100.0, 2) if spend > 0 else 0.0,
            "subscription_spend": round(subscription_spend, 4),
            "subscription_spend_pct": round((subscription_spend / spend) * 100.0, 2) if spend > 0 else 0.0,
        }

    selected_sprint = sprint[0] if sprint and len(sprint) == 1 else None
    selected_quarter = quarter[0] if quarter and len(quarter) == 1 else None

    if selected_sprint:
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in rows:
            day_label = datetime.fromisoformat(item["commit_date"]).strftime("%Y-%m-%d")
            groups.setdefault(day_label, []).append(item)

        points: list[dict[str, Any]] = []
        for label, group_rows in groups.items():
            points.append(_build_trend_point(label, group_rows))
        points.sort(key=lambda item: item["label"])
        return {
            "mode": "sprint_daily",
            "title": f"Sprint Trend ({selected_sprint})",
            "points": points,
        }

    if selected_quarter:
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in rows:
            groups.setdefault(item["sprint"], []).append(item)

        points = []
        for label, group_rows in groups.items():
            points.append(_build_trend_point(label, group_rows))
        points.sort(key=lambda item: _sprint_sort_key(item["label"]))
        return {
            "mode": "quarter_sprints",
            "title": f"Sprint Spend Trend ({selected_quarter})",
            "points": points,
        }

    groups: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        groups.setdefault(item["quarter"], []).append(item)

    points = []
    for label, group_rows in groups.items():
        points.append(_build_trend_point(label, group_rows))
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
        "seniority_levels": sorted({item["seniority"] for item in rows if item.get("seniority")}, key=_seniority_sort_key),
        "quarters": sorted({item["quarter"] for item in rows if item.get("quarter")}),
        "sprints": sorted({item["sprint"] for item in rows if item.get("sprint")}, key=_sprint_sort_key),
        "team_projects": {team: sorted(list(projects)) for team, projects in team_projects.items()},
        "quarter_sprints": {
            quarter_key: sorted(list(sprints), key=_sprint_sort_key) for quarter_key, sprints in quarter_sprints.items()
        },
    }
