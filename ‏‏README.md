# DevScore

Web prototype for AI cost and PR-outcome intelligence.

## Structure

- `frontend/` - Next.js dashboard UI
- `backend/` - FastAPI analytics and AI endpoints
- `mock_commits.json` - source dataset (read-only)
- `metrics.txt` - metric logic guideline

## Run Backend

Open a PowerShell terminal for the backend.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:OPENAI_API_KEY="your-key"
$env:OPENAI_MODEL="gpt-4.1-mini"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8010
```

Notes:

- Replace `your-key` with your real OpenAI API key.
- Keep the quotation marks around the API key.
- `$env:OPENAI_API_KEY=...` is remembered only in the current PowerShell window. If you close the terminal, set it again next time.
- If `.venv` already exists and dependencies are already installed, you can skip `python -m venv .venv` and the `pip install` command.

Short backend restart command after setup:

```powershell
cd backend
$env:OPENAI_API_KEY="your-key"
$env:OPENAI_MODEL="gpt-4.1-mini"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8010
```

Backend health check:

```text
http://127.0.0.1:8010/health
```

The backend root URL may show `{"detail":"Not Found"}`. That is normal because the API does not define a `/` route.

If port `8010` is already in use, choose another port and use the same port in `NEXT_PUBLIC_API_BASE_URL` when starting the frontend.

## Run Frontend

Open a second PowerShell terminal for the frontend.

```powershell
cd frontend
npm.cmd install
$env:NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8010"
npm.cmd run dev
```

If `node_modules` already exists, you can skip `npm.cmd install`.

Open the dashboard URL printed by Next.js, usually:

```text
http://localhost:3000
```

Short frontend restart command after setup:

```powershell
cd frontend
$env:NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8010"
npm.cmd run dev
```

If you changed the backend port, update the frontend API base URL before running `npm.cmd run dev`:

```powershell
$env:NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:<backend-port>"
npm.cmd run dev
```

## Dataset Upload

The dashboard includes a **Data Source** card showing the current JSON filename in use.
You can upload a new JSON file there and it will replace `mock_commits.json` immediately.
