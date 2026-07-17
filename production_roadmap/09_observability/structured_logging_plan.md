# 09 - Observability: Structured Logging & Telemetry Plan

## 1. The Core Vulnerability: Blind Operations
Currently, the application reports errors and progress using standard Python `print()` statements or basic logging (e.g., in `scout_console_reporter.py` and `job_scout.py`). 

**Why this is dangerous:**
If the scraper fails overnight while processing 400 jobs, you will wake up to thousands of lines of raw text in your terminal. Trying to parse this text manually to figure out *which* specific job triggered a Gemini API crash or an XPath failure is like finding a needle in a haystack. Standard text logs cannot be easily queried.

## 2. The Implementation Plan for the Fix
*When executing this fix, isolate it on a feature branch (`feature/09-observability`).*

### Step 1: Implement `structlog`
We will replace the standard `logging` and `print()` calls with **Structured JSON Logging** using a library like `structlog`.
Instead of emitting text:
`"Error calling Gemini API on job ID 12345: Timeout"`
The system will emit a structured JSON object:
```json
{
  "event": "llm_api_failure",
  "level": "error",
  "provider": "gemini",
  "job_id": "12345",
  "error_type": "Timeout",
  "timestamp": "2026-07-17T03:00:00Z"
}
```

### Step 2: Global Exception Handling
In `main.py` and `serve_dashboard.py`, we will wrap the core event loops in a global exception handler. If a catastrophic crash occurs, it will serialize the entire stack trace into a JSON log file (`data/logs/crash_reports.jsonL`) before shutting down safely, guaranteeing no error is ever lost to a closed terminal window.

### Step 3: Local Log Viewer
Since the logs are now pure JSON, we can add a simple "Diagnostics" tab to the dashboard. The JS frontend can fetch the JSON logs and allow you to filter by `"level": "error"` or `"provider": "linkedin"` instantly, providing enterprise-grade observability without needing a heavy tool like Datadog.

## 3. Verification & Safeguards
We will intentionally introduce a crash (e.g., throwing a dummy network error inside `LinkedInScraper`) and verify that the exact crash payload, including the job metadata and stack trace, is successfully recorded in the JSON log file.
