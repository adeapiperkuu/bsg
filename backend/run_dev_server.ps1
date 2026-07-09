Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot
# Only watch app/ so edits to tests/ or scripts/ do not restart the API mid-request (Vite proxy 502).
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app --reload-delay 0.5
