# Job Scout Dashboard User Guide

## Opening Job Scout

Double-click **Job Dashboard** on the Windows desktop. The launcher starts the
local dashboard server and opens the app in the default browser.

The dashboard address is:

```text
http://127.0.0.1:8000/recommended_jobs_dashboard.html
```

If the browser opens before the server is ready, wait a moment and refresh.

## Recommended Daily Workflow

1. Open **Home** and check the actionable count.
2. Open **Jobs** and review Apply First jobs before Good Options.
3. Mark jobs **Applied** after submitting, or **Irrelevant** when they are not
   useful. Clicking the same status again clears it.
4. Open **Applications** to add stages, notes, interview details, or follow-up
   dates.
5. Open **Scout** and start the recommended LinkedIn multi-query Fresh run when
   the actionable queue needs new jobs.
6. Use **Runs & Logs** when a run stops early, fails, or produces surprising
   results.

## Jobs

The Jobs workspace updates while the scout runs.

- **Apply First**: strongest realistic opportunities.
- **Good Options**: worthwhile applications after the strongest roles.
- **Low Probability**: weaker or riskier matches kept for visibility.
- **Rejected**: deterministic blockers or inaccessible/invalid jobs.

Useful quick filters include Current Run, Easy Apply, Dutch Risk, Remote/Hybrid,
Applied, and Irrelevant.

Applied and Irrelevant decisions persist across future scout runs. Previously
known jobs are not duplicated as new records.

## Starting A Scout

Open **Scout** or use any **Run Scout** button.

The recommended defaults are:

- LinkedIn multi-query Fresh
- Human mode on
- Fresh mode on
- Smart Guard AI budget
- Saved location and search-query strategy

**Smart Guard** stops a low-yield run before it spends excessive AI calls.
**Deep Search** continues longer. **Off** disables AI-budget stopping for that
run. Browser pacing and job-board safety limits still apply.

Only one dashboard-launched scout can run at a time. Stop controls can request:

- stop after the current job;
- stop after the current page;
- stop now.

Interrupted Fresh runs keep resumable progress when the underlying scout
progress file is available.

## Profile, CV, And Strategy

Use **Profile & CV** for factual candidate information. Never claim a skill,
language level, credential, or work authorization that is not true.

Use **Job Strategy** for:

- primary and bridge career paths;
- fallback roles;
- hard blockers and soft risks;
- locations and salary expectations;
- search queries;
- Fresh Scout thresholds;
- full recruiter/scoring instructions.

Dashboard edits are versioned in the private local workspace.

## AI Settings And API Keys

Use **Settings** to choose an AI backend, model, and fallback order.

For API keys:

- a blank key field keeps the existing key;
- entering a value replaces the local key;
- using the remove action deletes that provider key;
- stored key values are never returned to the browser.

Use **Test connection** to verify provider access. Auto mode tries configured
providers in the displayed order and moves to the next provider after supported
transient failures or rate limits.

## Application Assistant

The Assistant stores reusable truthful answers and can create a free local
cover-letter draft. AI improvement happens only after explicitly clicking the
AI button.

Generated text is a draft. Review names, dates, experience, language claims,
salary, and job-specific assertions before using it.

## Runs, Logs, And Backups

**Runs & Logs** shows:

- workspace and SQLite index health;
- resume availability;
- saved terminal and dashboard-run logs;
- recent run history;
- the latest detected fatal/error signal.

Backups exclude secrets and session data. Log cleanup keeps recent logs and only
deletes files older than the selected conservative retention period.

## Manual Steps And Safety Boundaries

Job Scout deliberately does not:

- enter account credentials;
- solve or bypass CAPTCHA;
- bypass bot checks, rate limits, access controls, or paywalls;
- store cookies or session secrets in dashboard backups;
- submit the final application without human review.

When a job board requests login or verification, complete it manually in the
opened browser and then continue the run.

## Troubleshooting

**Dashboard says controller offline**

Close the tab and launch **Job Dashboard** from the desktop shortcut again.

**A run stopped early**

Check the stop reason on Jobs or Runs & Logs. Smart Guard, a manual stop,
provider limits, browser navigation timeouts, or site verification may explain
the stop.

**No actionable jobs appear**

The actionable view contains only unreviewed Apply First and Good Options jobs.
Switch Jobs to **All jobs**, clear filters, or start a new Fresh run.

**A job has the wrong Easy Apply status**

Easy Apply is detected passively from the LinkedIn detail page. Refreshing it
requires a future scout visit; the app never clicks the application button only
to detect it.
