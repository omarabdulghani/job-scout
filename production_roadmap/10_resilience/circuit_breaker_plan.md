# 10 - Resilience: Circuit Breaker & Exponential Backoff Plan

## 1. The Core Vulnerability: Fragile Retries
When you are dealing with external systems (LinkedIn, Indeed, Gemini API, Anthropic API), network instability is guaranteed. 
Currently, the application has basic `try/except` logic and standard retry loops for LLM failures. 

**Why this is dangerous:**
1. **IP Bans**: If LinkedIn aggressively blocks your IP during a scrape, a simple retry loop will aggressively hammer their server, virtually guaranteeing a permanent IP ban.
2. **API Rate Limits**: If Gemini returns an HTTP 429 (Too Many Requests), retrying immediately will continue to fail and drain your quota or get your API key suspended.
3. **Cascading Failures**: A failure in the LLM provider can cascade down and crash the entire scraper loop, losing the scraped jobs in memory before they are saved to SQLite.

## 2. The Implementation Plan for the Fix
*When executing this fix, isolate it on a feature branch (`feature/10-resilience`).*

### Step 1: The Circuit Breaker Pattern
We will implement a standard `CircuitBreaker` utility class (or use a library like `pyfailsafe` or `tenacity`).
This intercepts all network traffic. The state machine operates as follows:
- **CLOSED**: Traffic flows normally.
- **OPEN**: If 3 consecutive network failures happen (e.g., HTTP 429 or 503), the circuit "trips" and opens. For the next 15 minutes, any request to that specific API immediately returns a safe fallback without actually hitting the network, saving credits and preventing bans.
- **HALF-OPEN**: After 15 minutes, it lets 1 request through to test if the provider is back online. If it succeeds, it CLOSES.

### Step 2: Exponential Backoff
Instead of a linear retry (wait 1 second, retry. wait 1 second, retry), we will configure the retries to back off exponentially with jitter:
Wait 1s -> Wait 2s -> Wait 4s -> Wait 8s.
This is the industry standard for handling API rate limits gracefully.

### Step 3: Integrating the Safeguards
We will inject these resilience layers into:
1. The AI Clients (to handle LLM API limits).
2. The `BrowserController` (to handle LinkedIn IP bans and connection resets).

## 3. Verification & Safeguards
We will test the Circuit Breaker by intentionally setting an invalid API key. We will verify that the system fails fast after 3 attempts, transitions to the OPEN state, logs a structured error, and gracefully pauses the scraper rather than crashing the Python process.
