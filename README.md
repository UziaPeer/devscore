# DevScore

Web prototype for AI cost and PR-outcome intelligence.

## Structure

- `frontend/` - Next.js dashboard UI
- `backend/` - FastAPI analytics and AI endpoints
- `mock_commits.json` - source dataset (read-only)
- `metrics.txt` - metric logic guideline

## Why the API key error happens

The AI endpoints run in the backend (`/ai/*`).  
When the backend starts, it looks for `OPENAI_API_KEY` in environment variables.  
If the key is missing, it returns:

```json
{"detail":"OPENAI_API_KEY is required for AI endpoints."}
```

To avoid setting the key manually on every terminal restart, this project now auto-loads `backend/.env` at backend startup.

## One-Time Setup

Open PowerShell in the project root:

```powershell
cd C:\Users\תלמידים\Desktop\עוזיה\vscode\projects\DevScore
```

Create the backend virtual environment and install dependencies:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create `.env` from the example:

```powershell
Copy-Item .env.example .env
```

Edit `backend/.env` and set your real key:

```env
OPENAI_API_KEY=your-real-key
OPENAI_MODEL=gpt-4.1-mini
```

## Run Backend

From the `backend` folder:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8010
```

Backend health check:

```text
http://127.0.0.1:8010/health
```

Note: opening `http://127.0.0.1:8010` (without path) may return `{"detail":"Not Found"}`. That is normal.

## Run Frontend

Open a second PowerShell terminal:

```powershell
cd C:\Users\תלמידים\Desktop\עוזיה\vscode\projects\DevScore\frontend
npm.cmd install
$env:NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8010"
npm.cmd run dev
```

Open:

```text
http://localhost:3000
```

If `node_modules` already exists, you can skip `npm.cmd install`.

## Daily Restart (after full shutdown)

1. Backend terminal:

```powershell
cd C:\Users\תלמידים\Desktop\עוזיה\vscode\projects\DevScore\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8010
```

2. Frontend terminal:

```powershell
cd C:\Users\תלמידים\Desktop\עוזיה\vscode\projects\DevScore\frontend
$env:NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8010"
npm.cmd run dev
```

Because the backend now loads `backend/.env`, you no longer need to type `OPENAI_API_KEY` manually every time.

## Dataset Upload

The dashboard includes a **Data Source** card showing the current JSON filename in use.
You can upload a new JSON file there and it will replace `mock_commits.json` immediately.


## performance calculation


**Model Performance Score** is currently calculated as:

```
score = 0.35*LongevityScore + 0.30*BugFixScore + 0.20*LeadTimeScore + 0.15*IterationsScore
```

Each component is normalized to a 0–100 range based on the currently loaded dataset:

**LongevityScore:**
Higher = better.
Based on `longevity_days` (time until the first override; if there is no override, then up to a 60-day horizon after the last commit in the data).

**BugFixScore:**
Lower = better.
Based on `bugFixOverridesCount`.

**LeadTimeScore:**
Lower = better.
Based on `mergeDate - commitDate` in hours.

**IterationsScore:**
Lower = better.
Based on:

```
iterations_raw = revisionsBeforeMerge + commentsBeforeMerge / 4
```

---

Additionally, the following is calculated:

```
cost_performance_point = estimated_cost / max(score, 1.0)
```

And the cost (`estimated_cost`) is:

```
(input_tokens / 1e6) * input_price + (output_tokens / 1e6) * output_price
```

Where `input_tokens` and `output_tokens` are estimated from signals such as:
`revisions`, `comments`, `overrides`, `bugFixes`, and the prices are taken from `pricing.json`.

---

The actual implementation is in `analytics.py`.
