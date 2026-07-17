# 04 - Data Ops: Database Archiving Plan

## 1. The Core Vulnerability: Dashboard Lag & Database Bloat
The application currently syncs all job data from JSON files into a central SQLite database via `agent/operational_store.py`. 
As the scout runs continuously over weeks and months, the database will accumulate tens of thousands of jobs.

**Why this is dangerous:**
1. **Frontend Lag**: The live Vanilla JS dashboard tries to load and filter massive arrays of JSON objects. Once the database exceeds 5,000+ jobs, the browser memory will bloat, causing severe UI lag when filtering or sorting.
2. **Scout Slowdown**: `brain.py` and `job_scout.py` frequently query the local cache for deduplication. A bloated database slows down the `SELECT` queries during the active scraping pipeline.
3. **Storage Costs**: Unnecessary JSON strings stored directly in SQLite columns bloat the file size on disk.

## 2. The Implementation Plan for the Fix
*When we decide to execute this fix, we will isolate this work on a feature branch (per `EXECUTION_PROTOCOL.md`). We will implement a seamless archival system that moves dead weight out of the active database while keeping it accessible if needed.*

### Step 1: Create the Archival Schema
In `agent/operational_store.py` (or a new `agent/archive_store.py`), establish a connection to a secondary database file: `data/job_archive.db`. 
- Ensure the schema mirrors the active `job_scout.db` exactly.
- Add an `archived_at` timestamp column to track when a job was moved.

### Step 2: Implement the Archival Heuristics
We will write a new cron job or extend `agent/clean_expired.py` to identify jobs that are dead weight for the live dashboard.
A job will be flagged for archival if it meets ANY of the following criteria:
1. `manual_status` is explicitly set to `"irrelevant"` or `"rejected"`.
2. `scraped_at` is older than 90 days AND `manual_status` is not "applied" or "interviewing".
3. The job listing is confirmed dead/expired on LinkedIn/Indeed.

### Step 3: The Transactional Move
To ensure data integrity, the archival script will execute a strict SQLite Transaction:
1. `BEGIN TRANSACTION`
2. `INSERT INTO archive.jobs SELECT * FROM active.jobs WHERE [archival_heuristics]`
3. `DELETE FROM active.jobs WHERE [archival_heuristics]`
4. `COMMIT`
*(If the process crashes halfway, the transaction rolls back and no data is lost or duplicated).*

### Step 4: Dashboard UI Updates
We will add a toggle in the dashboard (`dashboard/app.js` and `dashboard/modules/settings.js`) labeled **"Include Archived Jobs"**. 
By default, this is disabled, keeping the UI lightning fast. If toggled on, the backend (`serve_dashboard.py`) will run a `UNION ALL` query across both the active and archive databases to return the full historical dataset.

## 3. Verification & Safeguards
Before merging this into `main`, we will write a unit test in `tests/test_operational_store.py` that mocks 10,000 jobs, executes the archival routine, and asserts that exactly the correct subset of jobs was migrated to the `archive.db` without data loss.
