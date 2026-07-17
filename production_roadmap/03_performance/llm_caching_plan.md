# 03 - Performance: Token Cost & LLM Caching Plan

## 1. The Core Vulnerability: Token Explosion & Redundancy
Currently, `brain.py` evaluates every single job by sending a massive prompt payload to the LLM. 
The payload consists of two parts:
1. **The System Prompt**: Your full CV, `profile.json`, scoring rules, and complex heuristics. (~3,000 tokens)
2. **The Job Description**: The raw text scraped from the job board. (~1,000 tokens)

**Why this is dangerous:**
- **Cost**: If you scout 100 jobs, you are paying for 400,000 input tokens. Over a month, this will drain API credits rapidly.
- **Latency**: Processing 4,000 tokens per request takes significantly longer than processing 1,000 tokens.
- **Redundancy**: If a company posts the exact same job twice (or if you run the scout on consecutive days and see the same job again), the agent pays for the exact same LLM analysis twice.

## 2. The Implementation Plan for the Fix
*When we decide to execute this fix, we will follow this structured, isolated sequence to implement caching without altering the core intelligence of the agent.*

### Step 1: Implement Local Hash Caching (The Database Layer)
We will create a fast, local SQLite cache that prevents the LLM from ever seeing the same job twice.
1. **Schema Update**: In `agent/operational_store.py`, create a new table `llm_eval_cache`.
2. **Hash Generation**: Before sending a job to the LLM, hash the `company_name` + `job_title` + `job_description` using SHA-256.
3. **Cache Hit Logic**: Check the database for this hash. If it exists, instantly return the previously calculated JSON score and reasoning.
4. **Cache Miss Logic**: Call the LLM, then write the resulting JSON and the hash into the database for future runs.

### Step 2: Implement Anthropic Prompt Caching (The Network Layer)
Even for new, unseen jobs, sending your 3,000-token System Prompt every time is wasteful. Anthropic's API supports **Prompt Caching**, which drops the cost of repetitive system prompts by 90%.
1. **Payload Restructuring**: In `agent/brain.py` (or the refactored `claude_client.py`), split the prompt payload strictly into a `system` block and a `user` block.
2. **Cache Headers**: Add the required `"cache_control": {"type": "ephemeral"}` parameter to the `system` block of the API request.
3. **Execution**: The Anthropic servers will cache your massive CV and rules for 5 minutes. Subsequent job evaluations within that window will only pay for the new 1,000-token job description.

### Step 3: Telemetry & Monitoring
We cannot optimize what we cannot measure. We will add telemetry to ensure the caching is actually working.
1. Update the terminal output (`scout_console_reporter.py`) to show:
   `Jobs Processed: 50 | Cache Hits: 12 | Token Savings: $0.15`
2. Log API latency to confirm that cached LLM calls are returning faster.

## 3. Verification & Safeguards
- **Cache Invalidation**: We must ensure that if you change your `profile.json` or `preferences.json`, the local hash cache automatically invalidates, forcing the LLM to re-evaluate jobs based on your new rules. This will be done by including a hash of your profile in the cache key.
- **Dry Run Testing**: Before merging this branch, we will run the scout on a previously scraped dataset to verify that exactly 100% of the jobs hit the local cache and 0 API calls are made.
