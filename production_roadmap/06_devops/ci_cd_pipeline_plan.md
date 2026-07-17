# 06 - DevOps: GitHub Actions CI/CD Pipeline Plan

## 1. The Core Vulnerability: Manual Testing & Regression Risks
Currently, you have a massive and highly robust test suite (32 test files containing 267 unit tests). 
However, running these tests is entirely manual (`python -m unittest discover tests`). 

**Why this is dangerous:**
1. **Human Error**: If you or another contributor makes a quick "one-line fix" and forgets to run the test suite locally before pushing to GitHub, you could unknowingly break the core scraping or scoring logic.
2. **Environment Drift**: A test might pass on your specific Windows machine because you have a hidden environment variable set locally, but fail on another developer's machine or a production server.
3. **Accidental API Usage**: If someone forgets to mock the LLM or Playwright modules properly in a future test, running the suite could accidentally spin up a real browser or drain your real API credits.

## 2. The Implementation Plan for the Fix
*When we execute this fix, we will isolate the work on a feature branch (per `EXECUTION_PROTOCOL.md`). We will implement an automated pipeline that runs your 267 tests in the cloud completely free of charge, every time a change is made.*

### Step 1: The Pipeline Configuration
We will create a specific YAML file required by GitHub: `.github/workflows/test.yml`.
This pipeline will trigger automatically on two events:
1. Every time code is pushed to the `main` branch.
2. Every time a Pull Request is opened against the `main` branch.

### Step 2: Defining the Cloud Environment
The YAML file will define an isolated Linux runner (`ubuntu-latest`) to prove that your code works cross-platform (since you currently code on Windows). 
It will use the `actions/setup-python` action to install exactly Python 3.12, matching your local environment.

### Step 3: Fast Dependency Caching
Installing Playwright and all dependencies from `requirements.txt` can take minutes. To keep the pipeline under 20 seconds, we will configure GitHub Actions caching:
```yaml
- uses: actions/cache@v3
  with:
    path: ~/.cache/pip
    key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements.txt') }}
```

### Step 4: Strict Environment Isolation
To guarantee that the tests *never* accidentally hit Anthropic, Gemini, or OpenAI (which would fail in the cloud anyway without the keys, or worse, leak real keys), the YAML file will inject strict dummy variables into the cloud environment:
```yaml
env:
  GEMINI_API_KEY: "dummy-key-for-testing"
  ANTHROPIC_API_KEY: "dummy-key-for-testing"
  OPENAI_API_KEY: "dummy-key-for-testing"
  TEST_MODE: "true"
```

### Step 5: The Execution Step
The final step in the pipeline runs the exact command you run locally:
```yaml
- name: Run 267 Unit Tests
  run: python -m unittest discover tests
```

## 3. Verification & Safeguards
After creating the YAML file, we will push the feature branch to GitHub. We will actively monitor the "Actions" tab on your GitHub repository. The branch will only be merged into `main` after we witness the cloud runner successfully spin up, cache the dependencies, and pass all 267 tests (showing a green checkmark next to your commit).
