# JobFlow — Local Job Discovery & Tailoring Pipeline

JobFlow is a local, single-user job discovery, scoring, and resume-tailoring pipeline. It automatically aggregates job listings from configured sources, scores them against your specific profile, sends review digests to your Telegram, logs approved positions to Notion, and builds customized application packets (resumes, cover letters, and application form answers) using the DeepSeek API.

---

## Project Structure

Here is a quick overview of the repository layout:

```text
jobflow/
├── config/                  # Configuration YAML files (user profile, search queries)
│   ├── profile.yaml         # User resume summaries, skills, experience, and preferences
│   └── sources.yaml         # List of target job boards, limits, and query details
├── data/                    # Local storage and offline assets
│   ├── fixtures/            # Sample files for dry-runs (e.g., sample_jobs.json)
│   └── playwright_profile/  # Persisted login sessions for headless scraping
├── jobflow/                 # Core Python source package
│   ├── __init__.py          # Package initialization
│   ├── __main__.py          # Executable entry point
│   ├── browser_sources.py   # Browser-based scrapers (LinkedIn, Naukri, Indeed, etc.)
│   ├── cli.py               # Click Command Line Interface & options
│   ├── config.py            # Environment loader and AppConfig configuration mapping
│   ├── models.py            # Dataclasses (JobListing, Profile, JobScore, ApplicationPacket)
│   ├── notion.py            # Notion API integration for tracking applications
│   ├── pipeline.py          # Orchestrates scraping, scoring, notifying, and saving
│   ├── scoring.py           # Job description matching algorithms (keyword overlap)
│   ├── sources.py           # Standard HTTP API feed crawlers (Greenhouse, Lever)
│   ├── store.py             # SQLite database layer storing jobs and review decisions
│   ├── tailor.py            # Resume-tailoring agent using the DeepSeek API
│   ├── telegram.py          # Telegram bot integrations for digests and reviews
│   └── utils.py             # Utilities for HTML stripping, env parsing, and files
├── outputs/                 # Directory containing generated resume packets and logs (Ignored)
│   └── packets/             # Custom tailored resumes (PDF, DOCX, Markdown)
├── resume/                  # Input template resumes
│   └── base.docx            # Base resume file used for custom overlays
├── tests/                   # Automated unit test suite
│   ├── test_config.py       # Validates profile.yaml, sources.yaml, and AppConfig
│   ├── test_pipeline.py     # Asserts dry-run pipeline flow and packet generation
│   ├── test_scoring.py      # Tests the scoring math against sample job criteria
│   ├── test_sources.py      # Checks source loading and parsing logic
│   └── test_store.py        # Asserts SQLite operations (loading/saving listings)
├── .env                     # Local environment keys and configuration (Ignored)
├── .env.example             # Template for creating local .env files
├── .gitignore               # Excludes secrets, caches, database files, and output packets
└── pyproject.toml           # Python package dependencies and build definitions
```

---

## File & Folder Usage Guide

### 📂 Core Packages & Modules (`jobflow/`)
* **`__init__.py`** & **`__main__.py`**: Configures the root namespace and enables running the application directly using python (`python -m jobflow`).
* **`cli.py`**: Definess subcommands for interaction:
  * `run`: Crawls jobs, matches against profile, and triggers notifications.
  * `login`: Interactively logs into job boards to store cookies.
  * `poll`: Reads user callbacks from Telegram bot digest buttons.
  * `doctor`: Runs diagnostic checks on configuration files and credentials.
  * `build-packet`: Re-generates tailored material from a specific job fingerprint.
* **`config.py`**: Integrates `.env` and YAML config files into an immutable typed `AppConfig` runtime settings schema.
* **`models.py`**: Houses core domain models for typing safety (JobListing, Profile, JobScore, etc.) throughout the workflow.
* **`pipeline.py`**: Contains `JobFlowPipeline` which ties the components together: runs search crawlers, saves new postings, triggers matching, sends digests, updates Notion, and outputs tailored resume packets.
* **`scoring.py`**: Scores how well listings match your profile using skill checks, target role matches, locations, and seniority indicators.
* **`sources.py` & `browser_sources.py`**: Implements targeted scraping routines. `sources.py` contains basic REST feed helpers, while `browser_sources.py` drives Playwright to log in and scrape modern interactive platforms.
* **`store.py`**: Interacts with the local SQLite DB (`jobflow.db`) to deduplicate listings, save decisions, and track status.
* **`tailor.py`**: Generates a tailored professional summary, custom cover letter, targeted cold email, and optimal form answers using the DeepSeek Chat Completions endpoint.
* **`telegram.py`**: Implements notifications, routing job matching digests containing inline "Approve", "Review", and "Skip" commands to your Telegram.
* **`notion.py`**: Exports details of approved positions to a designated Notion database.
* **`utils.py`**: Holds general helper functions for formatting and scrubbing data.

### 📂 Configuration (`config/`)
* **`profile.yaml`**: The single source of truth for your professional profile (skills, history, location preferences, salary goals, and resume path).
* **`sources.yaml`**: Governs search limits, location filters, page caps, and queries for enabled job boards.

### 📂 Tests (`tests/`)
* Contains full coverage tests asserting the pipeline configurations, storage drivers, scoring metrics, and PDF rendering processes.

---

## Setup and Quick Start

1. **Install Dependencies**:
   ```bash
   pip install .
   ```
2. **Add Credentials**:
   Copy `.env.example` to `.env` and add your DeepSeek API key (`DEEPSEEK_API_KEY`), Notion details, and Telegram bot tokens.
3. **Interactive Login**:
   Ensure Playwright session caches are created for scraping targets:
   ```bash
   python -m jobflow login
   ```
4. **Execution**:
   Run a dry-run check:
   ```bash
   python -m jobflow run --dry-run
   ```
   Or run the live job crawler pipeline:
   ```bash
   python -m jobflow run
   ```
5. **Poll Reviews**:
   ```bash
   python -m jobflow poll
   ```
