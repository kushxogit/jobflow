# JobFlow

JobFlow is your personal, automated job discovery and application pipeline. It finds relevant job postings from various platforms, scores them based on your resume, sends alerts to your Telegram, tracks them in Notion, and helps you apply automatically.

## Quick Start

### 1. Installation
Install the required dependencies:
```bash
pip install -e .
```

### 2. Configuration
Copy the environment template and fill in your API keys (DeepSeek, Notion, Telegram):
```bash
cp .env.example .env
```
Next, customize your professional profile and target job sources by editing the files in the `config/` directory:
- `config/profile.yaml`: Your skills, experience, and preferences.
- `config/sources.yaml`: Target job boards and search queries.

### 3. Usage

**Interactive Login (for scrapers):**
Log into job boards like LinkedIn to save a session for the scraper:
```bash
python -m jobflow login
```

**Run the Job Crawler:**
Run the pipeline once to discover, score, and process new jobs:
```bash
python -m jobflow run
```

**Run Continuously (Daemon):**
Run JobFlow as a background service that scrapes periodically and handles Telegram review callbacks:
```bash
python -m jobflow daemon --interval-hours 4
```

**View the Dashboard:**
Launch the interactive dashboard to view your job pipeline metrics and history:
```bash
streamlit run dashboard.py
```
