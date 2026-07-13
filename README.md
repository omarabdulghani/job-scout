# Job Scout

Job Scout is a local, GUI-first job-search workspace. It searches approved job
boards, filters and scores jobs against a private profile, updates a live
dashboard, and keeps application progress and run history in one place.

The dashboard is the primary interface. Terminal commands remain available for
recovery and development, but normal daily use does not require them.

## Project Motivation

I found manual job hunting to be highly inefficient and opaque. I wanted to learn modern AI-assisted development (Cursor/Claude Code) while solving a real problem, so I built an automated agent to scrape, score, and track job applications based on my exact profile. Treating this like a full-scale product build allowed me to master AI prompting, state management, and API integrations.

## Tech Stack

- **Backend**: Python 3.10+, SQLite (Operational indexing)
- **Frontend**: HTML, Vanilla JavaScript, CSS (Local GUI Dashboard)
- **Automation**: Playwright (Asynchronous headless DOM interaction)
- **AI Integrations**: Claude, OpenAI, Gemini, Cerebras, Ollama (via unified API fallback architecture)

## Technical Highlights

- **Resilient AI-Scoring Engine (`agent/brain.py`)**: Built a modular AI evaluation engine that parses job descriptions and falls back to different API providers seamlessly if one hits a rate limit or fails.
- **Privacy-First Architecture**: Designed a local operational SQLite database and isolated `user_workspace` to ensure sensitive API keys, cookies, and private CV metadata are never pushed to the public repo.
- **Asynchronous Workflows**: Engineered multi-query asynchronous extraction pipelines using Playwright to bypass common DOM bottlenecks while maintaining accurate scraping parameters.

## Start The App

On this Windows installation, double-click:

```text
C:\Users\oabd3\Desktop\Job Dashboard.lnk
```

The shortcut runs `start_dashboard.ps1`, starts the local server when needed,
and opens:

```text
http://127.0.0.1:8000/recommended_jobs_dashboard.html
```

The server listens only on the local computer.

## Dashboard Workspaces

- **Home**: next actions, profile readiness, latest run, and application totals.
- **Jobs**: live recommendations, filters, Easy Apply detection, and manual
  Applied/Irrelevant status.
- **Scout**: approved LinkedIn and Indeed workflows, Fresh mode, resume, stop,
  browser, location, and AI-budget controls.
- **Profile & CV**: personal profile, experience, education, skills, languages,
  work authorization, and the active CV.
- **Job Strategy**: target paths, bridge roles, blockers, salary rules,
  locations, search queries, and Fresh Scout thresholds.
- **Applications**: stages, notes, interviews, offers, and follow-up dates.
- **Assistant**: truthful reusable answers and local or explicitly requested
  AI-assisted cover-letter drafts.
- **Runs & Logs**: diagnostics, saved logs, run history, backups, and cleanup.
- **Settings**: AI providers, fallback order, API-key management, job boards,
  browser defaults, and application safety.

See [Dashboard User Guide](docs/dashboard_user_guide.md) for the complete
nontechnical workflow.

## Safety And Privacy

- Credentials are never entered automatically or stored by the app.
- Login, CAPTCHA, verification, and access checks remain manual.
- No anti-bot, paywall, rate-limit, or access-control bypass is implemented.
- API keys remain in the local `.env` file. The browser receives only a
  configured/not-configured signal, never the stored key value.
- Final application submission pauses for human review.
- The local backup tool excludes API keys, cookies, browser profiles, session
  data, and the operational SQLite index.
- Private profile, CV metadata, learned answers, and settings are stored under
  `data/user_workspace/`, which is ignored by Git.

## Data And Recovery

The live dashboard uses:

```text
recommended_jobs_dashboard.html
recommended_jobs_dashboard_data.json
recommended_jobs_dashboard_user_state.json
data/user_workspace/job_scout.db
```

JSON remains the recovery source. SQLite is an incremental local index for
growing operational data such as jobs, runs, and applications.

Saved run logs live in `logs/`. Secret-free backups live in `backups/`.

## Supported Scout Workflows

- LinkedIn multi-query Fresh Scout
- LinkedIn single-query scout
- LinkedIn process-only scoring
- Indeed description extraction

LinkedIn remains the primary and recommended workflow. Indeed keeps manual
login and verification and does not include bypass logic.

## AI Scoring

The dashboard supports the existing provider adapters:

- Cerebras
- Ollama Cloud
- Gemini
- Claude
- OpenAI-compatible endpoints
- LM Studio

`Auto` mode tries enabled providers in the configured fallback order. Provider
availability can be tested from Settings without spending a scoring request.
The per-run AI budget can use Smart Guard, Deep Search, or Off.

## Developer Setup

Requirements:

- Python 3.10+
- Playwright and the browsers used by the selected workflow

Install:

```powershell
python -m pip install -r requirements.txt
playwright install chromium
```

Start the dashboard manually:

```powershell
python serve_dashboard.py
```

Run tests:

```powershell
python -m unittest discover -s tests -p "test*.py"
```

## Important Files

```text
serve_dashboard.py                  Local GUI controller and API
recommended_jobs_dashboard.html     Main application UI
start_dashboard.ps1                 Desktop launcher
agent/job_scout.py                  Scout filtering and processing
agent/brain.py                      AI scoring and application intelligence
agent/user_workspace.py             Private workspace management
agent/operational_store.py          SQLite operational index
search_queries.txt                  Source/default query list
config/profile.json                 Source/default profile
config/preferences.json             Source/default preferences
```

Source/default files remain useful for development and first-run initialization.
Normal edits made through the dashboard are stored in the private workspace.
