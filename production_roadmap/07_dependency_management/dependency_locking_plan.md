# 07 - Dependency Management & Reproducible Builds

## 1. The Core Vulnerability: Dependency Drift
Currently, the project relies on a standard `requirements.txt` file (e.g., `playwright`, `langchain`, `google-genai`). 

**Why this is dangerous:**
In Python, if you do not strictly lock your sub-dependencies, running `pip install -r requirements.txt` on a new computer (or a cloud server) will pull the latest versions of libraries. If `playwright` releases an update tomorrow that deprecates a function we use, the app will instantly crash for anyone trying to run it. This is known as "Dependency Drift."

## 2. The Implementation Plan for the Fix
*When executing this fix, isolate it on a feature branch (`feature/07-dependency-management`).*

### Step 1: Migrate to Poetry or UV
We will replace `requirements.txt` with a modern Python package manager like `Poetry`.
1. Run `poetry init` to create a `pyproject.toml` file.
2. Port all dependencies from `requirements.txt` into the TOML configuration.
3. Run `poetry lock` to generate a `poetry.lock` file.

### Step 2: Commit the Lockfile
The `poetry.lock` file acts as a mathematical guarantee. It hard-codes the exact hashes and sub-versions of every library installed right now. We will commit this file to Git. 

### Step 3: Update Execution Scripts
Update `start_dashboard.ps1` and any documentation to reflect the new execution command. Instead of `python main.py`, the app will be executed within an isolated virtual environment via `poetry run python main.py`.

## 3. Verification & Safeguards
We will run `poetry install` in a completely empty directory. If the app boots and `python -m unittest` passes perfectly, we have proven that the build is 100% reproducible anywhere in the world.
