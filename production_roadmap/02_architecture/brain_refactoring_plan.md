# 02 - Architecture: brain.py Refactoring Plan

## 1. The Core Vulnerability: Monolithic Architecture
Currently, `agent/brain.py` is nearly 5,000 lines long and contains **146 separate methods** within a single `JobBrain` class. 

From an engineering perspective, this violates the Single Responsibility Principle (SRP). The file is simultaneously handling:
1. **Network IO & Retries** (Calling Claude, Gemini, Cerebras, Ollama, OpenRouter).
2. **Business Logic & Heuristics** (Keyword scoring, deduplication logic).
3. **Prompt Engineering** (Massive f-strings containing instructions and rules for the AI).
4. **Data Normalization** (Parsing JSON responses and handling schema errors).

**Why this is dangerous:**
If you want to update a prompt rule, you have to scroll through 5,000 lines of Python. If you want to add a new AI provider (like DeepSeek v3), you risk breaking the core business logic. If a syntax error occurs while editing a prompt, the entire application crashes.

## 2. The Implementation Plan for the Fix
*When we decide to execute this fix, we will follow this structured architectural extraction. We will do this safely in isolated steps to ensure the scout continues working.*

### Safe Execution Protocol
Before any code is modified, we will isolate this massive refactor in a parallel branch:
```bash
git checkout -b feature/02-architecture-brain-refactor
```
If the execution fails, we can instantly revert to safety with `git checkout main`. If it succeeds and all 267 tests pass, we will merge it.

### Phase 1: API Client Extraction
We will create a new directory: `agent/ai_clients/`.
We will extract all provider-specific HTTP calls, error handling, and rate-limiting out of `brain.py` into dedicated, modular classes:
- `agent/ai_clients/base_client.py` (Abstract interface)
- `agent/ai_clients/gemini_client.py`
- `agent/ai_clients/claude_client.py`
- `agent/ai_clients/cerebras_client.py`
- `agent/ai_clients/ollama_client.py`

### Phase 2: Externalizing Prompts
We will create a new directory: `agent/prompts/`.
Instead of massive Python f-strings, we will use Jinja2 templating to store our prompts as raw markdown/text files.
- `agent/prompts/system_instruction.j2`
- `agent/prompts/job_scoring_task.j2`

`brain.py` will simply use the Jinja2 library to render these text files and pass them to the AI clients. This allows you to edit prompts just like a normal text document without touching Python code.

### Phase 3: The `JobBrain` Simplification
`brain.py` will be reduced from 5,000 lines to roughly 500 lines. Its only job will be:
1. Receiving a job from the scraper.
2. Rendering the prompt via the Jinja templates.
3. Handing the prompt to the correct AI Client.
4. Returning the parsed JSON score back to the scout. 

## 3. Verification & Safeguards
Before we execute this refactor, we will implement the **Mock API Tests** (from our upcoming CI/CD pipeline plan) so that we can run the test suite locally and guarantee that the refactored `brain.py` produces the exact same JSON schema outputs as the monolithic version.
