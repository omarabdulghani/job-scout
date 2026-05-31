# Live Recommended Jobs Dashboard Data Contract

Status: proposed v1 contract for the live dashboard pipeline.

## Purpose

The live dashboard should always be one stable dashboard that updates during every scout run. It should preserve historical runs, allow filtering by run/date, decision bucket, domain category, and risk flags, and keep the existing final scout outputs working.

This contract defines the JSON data shape that the live writer will update after each terminal job decision.

## Canonical Files

Use one stable user-facing dashboard:

- `recommended_jobs_dashboard.html`
- `recommended_jobs_dashboard_data.json`
- `recommended_jobs_dashboard_user_state.json`

The HTML file reads and polls the live JSON file. The live JSON file is owned by
the scout and may be updated while a run is active.

Manual user progress such as Applied or Irrelevant is saved separately in
`recommended_jobs_dashboard_user_state.json`. Keeping manual status separate
prevents live scout writes from overwriting human review decisions.

For a read-only dashboard, `python -m http.server 8000` is enough. For saved
manual status, use the local-only dashboard server:

```powershell
python serve_dashboard.py
```

The server binds to `127.0.0.1` by default and exposes:

- `GET /api/dashboard-data`: live scout data merged with manual status.
- `GET /api/user-state`: raw manual status file.
- `POST /api/job-status`: save `applied`, `irrelevant`, or `unreviewed`.
- `GET /api/run-control`: local scout controller state and log tail.
- `POST /api/run-control/start`: start one approved scout workflow.
- `POST /api/run-control/stop`: request `after_current_job`, `after_current_page`, or `now`.

Run control is intentionally local-only and allowlisted. The dashboard never
accepts arbitrary shell commands and never displays credentials, API keys,
cookies, or tokens.

The existing final outputs should remain separate:

- `high_success_probability_jobs.json`
- `high_success_probability_jobs_multi.json`
- `recommended_jobs.html`
- debug/rejected/cache files

## Top-Level JSON Shape

```json
{
  "schema_version": "live_dashboard.v1",
  "dashboard_generated_at": "2026-05-26T14:03:00+02:00",
  "dashboard_updated_at": "2026-05-26T14:09:31+02:00",
  "active_run_id": "run_2026-05-26_140300",
  "runs": [],
  "jobs": [],
  "summary": {},
  "filter_options": {}
}
```

## Run Record

Each scout invocation creates one run record. Multi-query runs still count as one run, with each job carrying its query.

Required fields:

```json
{
  "run_id": "run_2026-05-26_140300",
  "run_number": 1,
  "run_label": "Run 1 - 2026-05-26 14:03",
  "started_at": "2026-05-26T14:03:00+02:00",
  "completed_at": "",
  "status": "running",
  "mode": "linkedin_scout_multi",
  "board": "linkedin",
  "location": "Amstelveen",
  "max_pages": "2",
  "queries": ["junior ux designer", "data analyst"],
  "stats": {
    "processed_jobs": 0,
    "apply_first": 0,
    "good_options": 0,
    "low_probability": 0,
    "rejected": 0
  }
}
```

Allowed `status` values:

- `running`
- `completed`
- `stopped`
- `failed`

## Job Record

Every job should be written when it reaches a terminal decision. That includes accepted AI-scored jobs, low-score jobs, deterministic rejects, invalid URLs, duplicate/cached recommendations, and AI errors.

Required fields:

```json
{
  "event_id": "run_2026-05-26_140300:linkedin_job_id:123456789",
  "run_id": "run_2026-05-26_140300",
  "run_label": "Run 1 - 2026-05-26 14:03",
  "processed_at": "2026-05-26T14:09:31+02:00",
  "board": "linkedin",
  "query": "junior ux designer",
  "page_number": 1,
  "job_index": 7,
  "title": "Junior UX Designer",
  "company": "Example Company",
  "location": "Amsterdam, Netherlands",
  "url": "https://www.linkedin.com/jobs/view/123456789/",
  "job_id": "123456789",
  "decision_category": "APPLY_FIRST",
  "decision_label": "APPLY FIRST",
  "score": 82,
  "domain_category": "UX_UI_PRODUCT_DESIGN",
  "domain_label": "UX/UI/Product Design",
  "reason": "Strong junior UX fit with realistic interview chance.",
  "flags": ["english_friendly", "training_based"],
  "source_stage": "ai_scored",
  "terminal_status": "accepted",
  "filter_notes": [],
  "ai": {
    "model": "gemini:gemini-2.5-flash",
    "match_tier": "strong_match",
    "cache_status": "new",
    "used_cv_second_stage": true
  }
}
```

Optional fields:

```json
{
  "salary_text": "EUR 2800-3200 per month",
  "employment_type": "full-time",
  "workplace_type": "hybrid",
  "description_preview": "Short cleaned job description preview...",
  "company_application_count_14_days": 1,
  "tracking_status": "saved_for_later",
  "tracking_updated_at": "2026-05-26T15:00:00+02:00"
}
```

## Decision Categories

Use these exact IDs so the UI filters stay stable:

| ID | Label | Meaning |
| --- | --- | --- |
| `APPLY_FIRST` | APPLY FIRST | AI score 70+ and no safety blocker. |
| `GOOD_OPTIONS` | GOOD OPTIONS | AI score 50-69, or human-review-worthy role. |
| `LOW_PROBABILITY` | LOW PROBABILITY | AI scored below 50, or AI could not confidently score after the description was available. |
| `REJECTED` | REJECTED | Deterministic hard reject, invalid URL, inaccessible job, hard language/seniority/location/license blocker, or current-student-only internship. |

Mapping rules:

- `score >= 70` -> `APPLY_FIRST`
- `50 <= score <= 69` -> `GOOD_OPTIONS`
- `score < 50` after AI scoring -> `LOW_PROBABILITY`
- Non-AI terminal reject -> `REJECTED`
- AI error after a usable description -> `LOW_PROBABILITY` with flag `ai_error`
- Invalid or inaccessible job URL -> `REJECTED`

## Domain Categories

Every job gets one primary domain category. If uncertain, use `OTHER`.

| ID | Label |
| --- | --- |
| `UX_UI_PRODUCT_DESIGN` | UX/UI/Product Design |
| `BRAND_CREATIVE_CONTENT` | Brand/Creative/Content |
| `ECOMMERCE_WEB_DIGITAL_OPS` | E-commerce/Web/Digital Ops |
| `DATA_ANALYTICS_BUSINESS` | Data/Analytics/Business Analyst |
| `CUSTOMER_SUCCESS_OPS_SUPPORT` | Customer Success/Ops/Support |
| `PRODUCT_PROJECT_OPERATIONS` | Product/Project/Operations |
| `PROCUREMENT_SUPPLY_CHAIN` | Procurement/Supply Chain |
| `RESEARCH_ADMIN` | Research/Admin |
| `MARKETING_COMMUNICATIONS` | Marketing/Communications |
| `FINANCE_LEGAL_COMPLIANCE` | Finance/Legal/Compliance |
| `FALLBACK_INCOME` | Fallback/Income |
| `OTHER` | Other |

Domain classification should be deterministic at first, based on title/query/description keyword groups. Later the AI reason can be used as supporting context, but the UI should not depend on an extra AI call.

## Flags

Flags are lowercase strings. They are used for quick filters and badges.

Recommended initial flags:

- `dutch_risk`
- `high_dutch_blocker`
- `commute_risk`
- `low_pay`
- `internship`
- `current_student_required`
- `training_based`
- `graduate_friendly`
- `english_friendly`
- `seniority_risk`
- `hard_seniority_blocker`
- `heavy_technical_requirement`
- `sales_cold_calling`
- `recruitment_pressure`
- `fallback_income`
- `strong_bridge_role`
- `creative_fit`
- `data_training_opportunity`
- `manual_review_needed`
- `ai_error`
- `cached_score`
- `duplicate_suppressed`
- `external_apply`
- `easy_apply`

## Apply Method

Each job may include:

- `easy_apply`: boolean
- `apply_method`: `easy_apply`, `external_apply`, or `unknown`
- `apply_method_label`: human-readable label for dashboard display

Older records without this field should be treated as `unknown`, not as
external apply.

## Summary Object

The writer should update summary counts after each job event.

```json
{
  "total_runs": 3,
  "total_jobs": 152,
  "active_run_jobs": 18,
  "by_decision": {
    "APPLY_FIRST": 8,
    "GOOD_OPTIONS": 24,
    "LOW_PROBABILITY": 31,
    "REJECTED": 89
  },
  "by_domain": {
    "UX_UI_PRODUCT_DESIGN": 12,
    "DATA_ANALYTICS_BUSINESS": 16,
    "OTHER": 5
  },
  "last_event_at": "2026-05-26T14:09:31+02:00"
}
```

## Filter Options

The dashboard can render filters directly from this object.

```json
{
  "runs": [
    {
      "run_id": "run_2026-05-26_140300",
      "label": "Run 1 - 2026-05-26 14:03",
      "date": "2026-05-26"
    }
  ],
  "decisions": [
    "APPLY_FIRST",
    "GOOD_OPTIONS",
    "LOW_PROBABILITY",
    "REJECTED"
  ],
  "domains": [
    "UX_UI_PRODUCT_DESIGN",
    "BRAND_CREATIVE_CONTENT",
    "OTHER"
  ],
  "flags": [
    "dutch_risk",
    "commute_risk",
    "low_pay"
  ]
}
```

## Identity And Deduplication

Use identity in this priority order:

1. LinkedIn/Indeed job ID
2. canonical job URL
3. normalized title + company + location

Within the same run, duplicate sightings should update the existing job record with extra queries/pages rather than create duplicate cards.

Suggested fields for duplicate tracking:

```json
{
  "seen_queries": ["junior ux designer", "product designer"],
  "seen_pages": [1, 2],
  "duplicate_count": 1
}
```

## Writer Rules

- Write JSON atomically: write to a temporary file, then replace the target file.
- Never store credentials, cookies, tokens, or browser session data.
- Keep one stable dashboard file and one stable JSON file.
- Preserve historical runs unless a future retention setting is explicitly added.
- Do not block the scout if the dashboard write fails; log a warning and continue.
- The HTML dashboard should poll the JSON every few seconds when served through `python -m http.server`.

## Next Implementation Step

Step 2 should create the live writer module that can:

1. start a run,
2. append/update a job event,
3. complete a run,
4. recompute summary/filter options,
5. write `recommended_jobs_dashboard_data.json` atomically.

The writer can be tested without browser automation by feeding synthetic job events into it.
