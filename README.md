# DevScore

Web prototype for AI cost and PR-outcome intelligence.

## Structure

- `frontend/` - Next.js dashboard UI
- `backend/` - FastAPI analytics and AI endpoints
- `mock_commits.json` - source dataset (read-only)
- `metrics.txt` - metric logic guideline

## Run Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Environment for AI endpoints:

```powershell
$env:OPENAI_API_KEY="your-key"
$env:OPENAI_MODEL="gpt-4.1-mini"
```

## Run Frontend

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Optional API base URL:

```powershell
$env:NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8000"
```

## Dataset Upload

The dashboard includes a **Data Source** card showing the current JSON filename in use.
You can upload a new JSON file there and it will replace `mock_commits.json` immediately.
