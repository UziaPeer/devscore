import json
import random
import hashlib
from datetime import datetime, timedelta

random.seed(42)

MODELS = {
    "GPT-4": 0.82,
    "Claude": 0.88,
    "Gemini": 0.74,
    "GPT-3.5": 0.58,
    "CodeLlama": 0.62
}

SENIORITY = {
    "Junior": 0.55,
    "2": 0.65,
    "3": 0.74,
    "4": 0.82,
    "Senior": 0.92
}

AUTHORS = [
    ("Daniel Cohen", "Junior", "Web"),
    ("Maya Levi", "Senior", "Trading"),
    ("Noam Azulay", "3", "Infrastructure"),
    ("Amit Peretz", "2", "Growth"),
    ("Yael Mizrahi", "4", "Payments"),
    ("Eli Ben-David", "Junior", "Mobile"),
    ("Shira Katz", "Senior", "Data"),
    ("Omer Klein", "3", "Web"),
    ("Tamar Shaked", "4", "Trading"),
    ("Ron Golan", "2", "DevOps"),
    ("Lior Avraham", "Senior", "Infrastructure"),
    ("Dana Bar", "Junior", "Growth"),
    ("Yossi Harel", "3", "Payments"),
    ("Adi Friedman", "4", "Mobile"),
    ("Guy Niv", "2", "Data"),
    ("Neta Weiss", "Senior", "DevOps"),
    ("Ido Sharabi", "Junior", "Web"),
    ("Hila Mor", "3", "Growth"),
    ("Barak Tal", "4", "Trading"),
    ("Chen Azulay", "2", "Infrastructure")
]

START_DATE = datetime(2024, 1, 1)
END_DATE = datetime(2025, 12, 31, 23, 59)


def generate_commit_hash(seed: str) -> str:
    return hashlib.sha1(seed.encode()).hexdigest()


def clamp(value, min_value, max_value):
    return max(min_value, min(value, max_value))


def quarter_start_dates(start_year=2024, end_year=2025):
    return [
        datetime(year, month, 1)
        for year in range(start_year, end_year + 1)
        for month in (1, 4, 7, 10)
    ]


def random_date_between(start_date, end_date):
    total_minutes = int((end_date - start_date).total_seconds() // 60)
    return start_date + timedelta(minutes=random.randint(0, total_minutes))


def random_commit_date(index):
    quarter_starts = quarter_start_dates()

    if index < len(quarter_starts):
        quarter_start = quarter_starts[index]
        next_quarter_start = (
            quarter_starts[index + 1]
            if index + 1 < len(quarter_starts)
            else END_DATE
        )
        quarter_end = min(next_quarter_start - timedelta(minutes=1), END_DATE)
        return random_date_between(quarter_start, quarter_end)

    return random_date_between(START_DATE, END_DATE)


def generate_mock_data(num_commits=1000):
    data = {}
    all_hashes = []
    quality_map = {}  # internal only

    for i in range(num_commits):
        author, seniority, team = random.choice(AUTHORS)
        model = random.choice(list(MODELS.keys()))

        model_quality = MODELS[model]
        seniority_quality = SENIORITY[seniority]

        quality_score = (model_quality * 0.55) + (seniority_quality * 0.45)
        quality_score += random.uniform(-0.08, 0.08)
        quality_score = clamp(quality_score, 0.1, 0.98)

        commit_date = random_commit_date(i)

        merge_delay_hours = int(random.uniform(2, 72) * (1.2 - quality_score))
        merge_date = commit_date + timedelta(hours=max(1, merge_delay_hours))

        revisions_before_merge = max(1, int(random.gauss(
            mu=1 + ((1 - quality_score) * 8),
            sigma=1.2
        )))

        comments_before_merge = max(0, int(random.gauss(
            mu=(1 - quality_score) * 18,
            sigma=3
        )))

        commit_hash = generate_commit_hash(f"{author}-{model}-{commit_date}-{i}")
        all_hashes.append(commit_hash)
        quality_map[commit_hash] = quality_score  # internal only

        data[commit_hash] = {
            "author": author,
            "authorSeniority": seniority,
            "team": team,
            "model": model,
            "commitDate": commit_date.isoformat() + "Z",
            "mergeDate": merge_date.isoformat() + "Z",
            "overriddenByCommits": [],
            "bugFixOverridesCount": 0,
            "revisionsBeforeMerge": revisions_before_merge,
            "commentsBeforeMerge": comments_before_merge
        }

    # Add override relationships
    for commit_hash in all_hashes:
        commit = data[commit_hash]
        quality = quality_map[commit_hash]

        override_probability = 0.25 + ((1 - quality) * 0.85)
        override_probability = clamp(override_probability, 0.15, 0.95)

        if random.random() < override_probability:
            possible_overriders = [
                h for h in all_hashes
                if data[h]["commitDate"] > commit["commitDate"]
            ]

            if possible_overriders:
                max_overrides = min(8, len(possible_overriders))
                min_overrides = min(2, max_overrides)

                num_overrides = random.randint(min_overrides, max_overrides)
                overridden_by = random.sample(possible_overriders, num_overrides)

                commit["overriddenByCommits"] = overridden_by

                bug_fix_count = 0
                for _ in overridden_by:
                    if random.random() < (1 - quality):
                        bug_fix_count += 1

                commit["bugFixOverridesCount"] = bug_fix_count

    return data


def generate_commit_groups(commits, sprint_length_days=14):
    sorted_commits = sorted(
        commits.items(),
        key=lambda item: item[1]["commitDate"]
    )
    first_commit_date = datetime.fromisoformat(
        sorted_commits[0][1]["commitDate"].replace("Z", "")
    ).date()

    groups = {
        "sprints": {},
        "quarter": {},
        "projects": {}
    }

    for commit_hash, commit in sorted_commits:
        commit_date = datetime.fromisoformat(
            commit["commitDate"].replace("Z", "")
        )

        sprint_number = ((commit_date.date() - first_commit_date).days // sprint_length_days) + 1
        sprint_key = f"Sprint {sprint_number:02d}"
        quarter_key = f"{commit_date.year}-Q{((commit_date.month - 1) // 3) + 1}"
        project_key = commit["team"]

        groups["sprints"].setdefault(sprint_key, []).append(commit_hash)
        groups["quarter"].setdefault(quarter_key, []).append(commit_hash)
        groups["projects"].setdefault(project_key, []).append(commit_hash)

    return groups


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


if __name__ == "__main__":
    mock_data = generate_mock_data(num_commits=100)
    grouped_commits = generate_commit_groups(mock_data)

    write_json("mock_commits.json", mock_data)
    write_json("mock_commits_grouped.json", grouped_commits)

    print(json.dumps(grouped_commits, indent=2))
