# Production Roadmap Execution Protocol

This protocol serves as the absolute law for executing any architectural changes, refactors, or feature additions described in this roadmap. 

**Rule #1: The Main Branch is Sacred**
The `main` branch must remain in a highly stable, 100% production-ready state at all times. We do not write, test, or execute roadmap plans directly on the `main` branch.

**Rule #2: The Branching Strategy**
Before executing any plan in this roadmap, you MUST spawn a parallel Git branch.

```bash
# Example: Executing the Architecture Refactor
git checkout -b feature/02-architecture-refactor
```

**Rule #3: The Revert Safety Net**
If an execution fails, causes cascading errors, or if you simply wish to abort the operation, do not attempt to manually undo the code changes. Instead, instantly revert to the sacred state:
```bash
# Instantly discard all changes and return to safety
git checkout main
git branch -D feature/02-architecture-refactor
```

**Rule #4: Verification & Merge**
A feature branch can only be merged into `main` if:
1. The implementation precisely matches the roadmap plan.
2. The `python -m unittest discover tests` suite runs and all 267+ tests pass successfully. 

```bash
git checkout main
git merge feature/02-architecture-refactor
```
