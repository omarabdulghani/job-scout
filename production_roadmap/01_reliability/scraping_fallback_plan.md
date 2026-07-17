# 01 - Scraping Fragility Audit & Fix Plan

## 1. The Core Vulnerability: Hardcoded DOM Selectors
The primary vulnerability lies at the top of `scrapers/linkedin.py` and `scrapers/indeed.py`. The scraper currently relies on a massive list of highly specific, hardcoded CSS selectors to navigate the DOM. 

Here is a snippet of the exact fragility points currently hardcoded in the system:

```python
# Lines 21-135 of scrapers/linkedin.py
RESULTS_RAIL_SELECTORS = [
    ".jobs-search-results-list",
    ".jobs-search-results__list",
    ".scaffold-layout__list-container",
]
CARD_SELECTORS = [
    ".job-card-container",
    ".jobs-search-results__list-item",
]
DESCRIPTION_SELECTORS = [
    ".jobs-description__content",
    ".jobs-box__html-content",
    ".jobs-description-content__text",
]
# Plus 8 other selector categories (Easy Apply, Salaries, Titles, etc.)
```

## 2. Why This Will Break
LinkedIn engineering teams employ heavy A/B testing, continuous deployments, and DOM obfuscation to prevent automated scraping:
1. **Class Name Rotation**: If LinkedIn switches from `.jobs-search-results-list` to a hashed class name (e.g., `.css-x8y9z`), the scraper will instantly fail to find jobs.
2. **DOM Restructuring**: If LinkedIn nests the job description inside an `<iframe>` or a Web Component Shadow DOM (which they are currently testing via `#interop-outlet`), traditional DOM traversal fails.
3. **Easy Apply Modal Variations**: The Easy Apply modal changes depending on the job poster's requirements (e.g., asking for custom text inputs instead of just a resume upload). The current hardcoded modal selectors will break if a new input type is introduced.

## 3. The Implementation Plan for the Fix
*When we decide to execute this fix, we will follow these structured, safe methods to ensure we do not break existing functionality.*

### Safe Execution Protocol
Before any code is modified, we will isolate this work in a parallel branch:
```bash
git checkout -b feature/01-scraping-fallback
```
If the execution fails, we can instantly revert to safety with `git checkout main`. If it succeeds, we will merge it.

**Step 1: Implement AI Parsing Engine**
Create a new utility class (e.g., `agent/dom_parser.py`) that handles sending raw HTML to a fast LLM (like Gemini 2.5 Flash) to identify dynamic CSS selectors.

**Step 2: Graceful Degradation in Scrapers**
Update `LinkedInScraper` methods to use a `try/except` fallback logic:
1. Attempt to use the existing hardcoded dictionaries (fast).
2. If elements are not found, take a DOM snapshot and invoke the `dom_parser`.
3. Cache the newly discovered selectors in memory for the duration of the scout run.

**Step 3: Verification & Safeguards**
- Ensure that the LLM is only invoked when absolutely necessary to prevent token cost explosion.
- Add logging to track when the fallback was triggered so the developer is alerted to permanent layout changes.
