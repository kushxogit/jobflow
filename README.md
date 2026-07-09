# JobFlow

JobFlow is your personal, automated job discovery and application pipeline. It intelligently finds relevant job postings from various platforms (e.g., LinkedIn, Indeed, Wellfound), uses AI models via OpenRouter to parse and score them based on your resume, tracks them locally in a SQLite database, and provides a modern Minimal Cybercore web dashboard for you to review and apply to jobs.

## Key Features
- **Intelligent AI Parsing**: Leverages OpenRouter to validate job listings, extract fields, and score them against your professional profile (`profile.yaml`). Features an acknowledgment-based fallback workflow to seamlessly rotate through free AI models.
- **Robust Playwright Crawling**: Emulates human behavior (typing, clicking) to accurately search job boards, bypassing restrictive filters to find precise locations (e.g., India, Remote) and job types.
- **Aesthetic Dashboard**: A highly responsive, minimal cybercore React interface built with Vite and powered by a blazing-fast FastAPI backend.
- **Automated Workflow**: Run once, or run as a background daemon to continuously discover and score jobs.

## Quick Start

### 1. Installation
Install the required Python dependencies:
```bash
pip install -e .
```
*(Ensure you have Node.js installed to run the frontend)*
Install the frontend dependencies:
```bash
cd ui
npm install
```

### 2. Configuration
Copy the environment template and fill in your API keys (e.g., DeepSeek, OpenRouter):
```bash
cp .env.example .env
```
Next, customize your professional profile and target job sources by editing the files in the `config/` directory:
- `config/profile.yaml`: Your skills, experience, and preferences.
- `config/sources.yaml`: Target job boards and search queries.

### 3. Usage

> **Note for Windows users:** If running `python` gives a "not found" error or opens the Microsoft Store, use `py` instead (e.g., `py -m jobflow ...`).

**Interactive Login (for scrapers):**
Log into job boards to save a session for the Playwright scraper:
```bash
py -m jobflow login
```

**Run the Job Crawler:**
Run the pipeline once to discover, score, and process new jobs:
```bash
py -m jobflow run
```

**Run Continuously (Daemon):**
Run JobFlow as a background service that scrapes periodically:
```bash
py -m jobflow daemon --interval-hours 4
```

### 4. View the Dashboard (Minimal Cybercore React App)
JobFlow now features a highly aesthetic, responsive React dashboard built with Vite and powered by a FastAPI backend.

**Start both Backend and Frontend together:**
```bash
py start_dashboard.py
```
Then, open `http://localhost:5173` in your browser to view your jobs! When you're done, just hit `Ctrl+C` in the terminal to gracefully shut both services down.
