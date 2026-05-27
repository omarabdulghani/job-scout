# AI Job Application Agent

An automated Python agent that searches LinkedIn, Indeed, and Glassdoor for jobs, scores them against your profile, and can apply using a real Playwright-controlled browser plus Claude.

## Current Status

What works today:
- Searches LinkedIn, Indeed, and Glassdoor
- Scores jobs using your profile and preferences
- Saves applications in SQLite
- Uses a persistent browser profile so logins can be reused
- Supports dry-run mode to search and score without applying
- Can optionally pause before final submission
- Can skip LinkedIn jobs unless they support Easy Apply
- Can skip assessment flows when configured

What is not implemented yet:
- Standalone job-site discovery is not implemented yet
- End-to-end reliability still depends on job-board selectors and the target site's form layout

## How It Works

1. You fill in `config/profile.json` and `config/preferences.json`
2. The agent searches enabled job boards
3. Jobs are scored locally against your preferences
4. Matching jobs are opened in a real browser
5. Claude looks at screenshots and page text to decide the next browser action
6. Applications are logged to `data/applications.db`

## Requirements

- Python 3.10+
- An Anthropic API key for application mode
- Playwright Chromium installed

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Add your API key

PowerShell:

```powershell
Copy-Item .env.example .env
```

Bash:

```bash
cp .env.example .env
```

Then edit `.env` and set:

```env
ANTHROPIC_API_KEY=your_key_here
```

Optional:

```env
ANTHROPIC_MODEL=claude-opus-4-5
```

Optional scout scoring backend:

```env
# Default scout scoring backend: Google AI Studio / Gemini
AI_BACKEND=gemini
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
GEMINI_MAX_OUTPUT_TOKENS=512
GEMINI_THINKING_BUDGET=0
GEMINI_MAX_ATTEMPTS=3

# Optional local LM Studio backend for scout scoring
LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
LMSTUDIO_MODEL=google/gemma-4-e4b
LMSTUDIO_REASONING_ENABLED=false
LMSTUDIO_REASONING_EFFORT=none

# Optional fallbacks
# AI_BACKEND=lmstudio
# AI_BACKEND=claude
```

Notes:
- `AI_BACKEND` only affects scout-mode interview-probability scoring.
- Application mode and browser-automation prompts still use Anthropic.
- When `AI_BACKEND=gemini`, the scout uses the Google AI Studio/Gemini API and requires `GEMINI_API_KEY`.
- Gemini scoring uses structured JSON output and keeps the response budget small because the scorer only needs a score plus one sentence.
- When `AI_BACKEND=lmstudio`, the scout fails clearly if LM Studio is unreachable or the model/config is invalid.
- For Gemma 4 E4B, the stable default is `LMSTUDIO_REASONING_ENABLED=false` with `LMSTUDIO_REASONING_EFFORT=none`.
- On real scout runs, the scorer logs the resolved LM Studio request settings once before the first AI call so you can verify the actual reasoning parameter and token budget being used.
- If you turn reasoning back on, the scout automatically uses a larger token budget for scoring responses.

### 3. Fill in your profile

Edit `config/profile.json` with your real information:
- Personal details
- Work experience
- Education
- Skills
- Salary expectations
- Common answers for application questions

### 4. Set your job preferences

Edit `config/preferences.json`:
- Target job titles
- Locations
- Remote / hybrid / onsite preferences
- Required / excluded / nice-to-have keywords
- Salary minimum
- Enabled job boards
- Application behavior flags

### 5. Add your CV

Place your CV at:

```text
cv/Omar Abdulghani - CV Resume (English).pdf
```

Or update `cv_path` in `config/profile.json`.

## Running the Agent

```bash
python main.py
python main.py --dry-run
python main.py --validate-boards
python main.py --stats
```

Notes:
- `--dry-run` searches and scores jobs but does not apply
- `--validate-boards` opens one representative search per enabled board and reports selector health
- `--stats` reads the application database and exits
- Application mode requires `ANTHROPIC_API_KEY`

## First Run and Login

On the first real run, a browser window opens and the agent will use a persistent browser profile stored in `data/browser_profile/`.

For LinkedIn, you may need to log in manually the first time. After that, the session should be reused automatically.

## Project Structure

```text
job_agent/
|-- main.py
|-- requirements.txt
|-- .env.example
|-- config/
|   |-- profile.json
|   `-- preferences.json
|-- cv/
|   `-- Omar Abdulghani - CV Resume (English).pdf
|-- agent/
|   |-- brain.py
|   |-- browser.py
|   |-- job_agent.py
|   `-- tracker.py
|-- scrapers/
|   |-- linkedin.py
|   |-- indeed.py
|   `-- glassdoor.py
`-- data/
    |-- applications.db
    `-- browser_profile/
```

## Important Settings

### Matching and Filters

- `job_titles`: titles to search and score against
- `keywords_required`: if none are found, the score is reduced
- `keywords_nice_to_have`: adds score when matched
- `keywords_exclude`: reduces score or filters poor matches
- `industries_preferred`: adds score when matched in the job text
- `industries_excluded`: reduces score when matched
- `companies_blacklist`: blocks applications to listed companies
- `companies_whitelist`: boosts trusted companies
- `salary_minimum`: minimum acceptable salary used during scoring
- `filters.posted_within_days`: affects search recency on supported boards
- `filters.min_match_score`: minimum score to apply

### Application Behavior

- `skip_if_already_applied`: skips jobs already recorded in the database
- `submit_cover_letter`: enables or disables cover-letter use
- `generate_cover_letter_with_ai`: asks Claude to generate a cover letter when enabled
- `answer_screening_questions`: allows AI-generated answers for screening questions
- `skip_assessments`: skips applications that lead into assessments
- `pause_before_final_submit`: pauses before final submission
- `add_human_like_delays`: keeps random delays between browser actions

### Job Boards

- `job_boards.linkedin.enabled`
- `job_boards.linkedin.easy_apply_only`
- `job_boards.indeed.enabled`
- `job_boards.glassdoor.enabled`
- `job_boards.standalone_sites.enabled`
  Note: this setting is currently a placeholder and is not implemented yet.

## Costs

Application mode uses Anthropic API calls for:
- Cover letter generation
- Page-by-page browser guidance
- Screening question answers when needed

Cost depends on the model and how many form pages each application requires.

## Limitations

- Standalone-site discovery is not implemented yet
- Job-board selectors can break when LinkedIn, Indeed, or Glassdoor change their layout
- Some external application flows may open unusual forms or anti-bot checks
- CAPTCHAs still require human intervention
- Very complex multi-step assessments are intentionally skipped when configured

## Recommended Workflow

1. Start with `python main.py --dry-run`
2. Run `python main.py --validate-boards` when you change selectors or job-board settings
3. Review the top scored jobs
4. Enable application mode only after the search results look right
5. Keep `pause_before_final_submit` enabled until you trust the flow
6. Check `python main.py --stats` regularly

## Safety and Privacy

- Do not commit `.env`, `data/`, or personal CV/profile files
- Review the Terms of Service for the sites you automate against
- Use moderate volume to reduce the chance of rate limits or account restrictions
