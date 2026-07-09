@echo off
echo Starting JobFlow FastAPI Backend...
start "JobFlow API" cmd /k "py -m uvicorn api:app --reload --port 8000"

echo Starting JobFlow Vite Frontend...
cd ui
start "JobFlow UI" cmd /k "npm run dev"

echo Both services have been started in separate windows!
echo You can view the dashboard at http://localhost:5173
pause
