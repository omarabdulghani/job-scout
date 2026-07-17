# 11 - SaaS Pivot: Multi-Tenant Architecture Plan

## 1. The Vision: From Personal Script to B2B SaaS
You have proposed pivoting the application from a "Single-Tenant" personal tool into a "Multi-Tenant" SaaS business. 
- **The Clients**: Have their own separate, simplified web portal where they upload their CV and set preferences.
- **The Admin (You)**: Have the "Engine Dashboard" where you trigger the AI agent to hunt jobs for them.
- **The Delivery**: The clients only see the final, filtered results in their portal.

## 2. Impact on the Existing Production Roadmap
This massive pivot **does not invalidate** the first 10 plans we made, but it acts as a "multiplier" for them. Here is exactly how it impacts our roadmap:

- **NO IMPACT (These are even more mandatory now)**
  - `01_reliability`, `02_architecture`, `03_performance`, `07_dependency`, `08_containerization`, `09_observability`, `10_resilience`.
  - Because you are now running the engine for *paying clients*, if LinkedIn bans the scraper or `brain.py` crashes, your business stops. These 7 engine-hardening plans are now absolutely mandatory.

- **SLIGHT IMPACT (Needs an extra column)**
  - `04_data_ops` (Database): The SQLite database must be updated. Every single table (Jobs, Runs, Logs) must now have a `user_id` column. If you don't add this, Client A will accidentally see Client B's job recommendations!

- **MASSIVE IMPACT (Needs a complete split)**
  - `05_frontend` (Vanilla JS Dashboard): The current dashboard is built for an Admin. We now need **two** frontends:
    1. **The Admin Engine** (What you see, to control the scrapers).
    2. **The Client Portal** (A brand new, simplified React/Next.js or Vanilla website with login, CV upload, and a read-only list of jobs).

## 3. The Implementation Plan for the SaaS Pivot
*When executing this pivot, we will follow these steps:*

### Step 1: The Database Pivot (Multi-Tenancy)
We will migrate SQLite to PostgreSQL (or keep SQLite but rewrite the schema). We must add `client_id` to the `profile.json` logic. `brain.py` will no longer read a single `profile.json` from the hard drive; it will query the database for the specific client's CV and preferences before scoring the job.

### Step 2: The API Pivot (FastAPI / REST)
The current `serve_dashboard.py` is tightly coupled to the local GUI. We will rewrite it into a true REST API using **FastAPI**. 
- `POST /api/clients/` (Create a new client)
- `POST /api/clients/{id}/upload-cv`
- `GET /api/clients/{id}/results` 
This API will be secured with JWT authentication so clients can only see their own data.

### Step 3: The Engine Pivot (Task Queues)
You cannot run 50 clients' searches sequentially in a single terminal. We will implement **Celery + Redis** (as mentioned in the Staff Engineer concepts). When you want to hunt for 10 clients, you click "Run All", and the system spins up 10 parallel background workers to scrape and score simultaneously.
