# Week 9: Advanced Agentic Orchestration & Browser Skill

This project represents an advanced agentic orchestration system capable of multi-step research, reasoning, and autonomous browser execution. It utilizes a dynamically growing Directed Acyclic Graph (DAG) to coordinate specialized cognitive skills—such as a Planner, Distiller, Critic, Formatter, and a multi-layered Browser—through a unified LLM Gateway.

## Core Architectural Components

### 1. Orchestrator (`flow.py`)
The orchestrator drives the execution loop by dynamically building a NetworkX `DiGraph` at runtime.
- **Concurrent Execution:** Uses `asyncio` to execute independent DAG branches in parallel, respecting data dependencies.
- **Critic Auto-Insertion:** Automatically splices `Critic` nodes after skills configured with `critic: true` (e.g., Distiller) to validate outputs before they reach the final Formatter.

### 2. Failure Recovery System (`recovery.py`)
A highly resilient exception-driven recovery system that classifies failures and adjusts the DAG dynamically.
- **Amnesia Fix:** When a recovery Planner is triggered (e.g., after a Critic rejects a hallucinated output), the orchestrator feeds the IDs of *previously successful nodes* into its context. This ensures the Planner attempts new strategies (like alternate URLs) rather than starting the entire task from scratch.

### 3. Browser Skill Cascade (`browser/skill.py`, `browser/driver.py`)
An autonomous, four-layer escalation cascade designed to fetch web content reliably:
- **Layer 1 (Extract):** Lightning-fast HTTP extraction via `trafilatura` (no LLM required).
- **Layer 2a (Deterministic):** Executes exact Playwright selectors (clicks/fills) if explicitly requested.
- **Layer 2b (A11y):** Uses the Accessibility tree to interact with DOM elements textually.
- **Layer 3 (Vision):** Uses a Set-of-Marks (SoM) approach to visually identify and interact with elements when the DOM is obscured.
- **Gateway Block Detection:** Proactively detects CAPTCHAs, Cloudflare interstitials, and login walls. It raises a fatal error immediately, forcing the orchestrator to replan with alternate URLs instead of wasting LLM tokens.

### 4. LLM Gateway (`llm_gatewayV9/`)
A centralized routing and failover service abstracting LLM providers from the orchestrator.
- **Failover & Cooldowns:** Seamlessly fails over to fallback candidates if a model returns a 503/404, placing the failing provider on a temporary cooldown.
- **Cost Tracking:** Maintains a SQLite ledger (`gateway_v8.db`) attributing token usage directly to DAG sessions.

## Usage & Demo

Make sure the LLM Gateway is running on port 8109:
```bash
cd llm_gatewayV9
uv run main.py
```

Run the orchestrator using `flow.py`:
```bash
cd code
uv run flow.py "Compare 3 laptops under ₹80,000."
```

Or run the predefined demos using `run_demo.sh`:
```bash
./run_demo.sh browser
./run_demo.sh tests
```

## Recent Fixes
- **Critic Recovery Amnesia**: The recovery Planner now successfully retains previously completed siblings when retrying an extracted branch.
- **Planner URL Fallback**: The Planner is explicitly prompted to change strategies and avoid retrying identical URLs when failing a Critic evaluation.
- **Optimized Browser Execution**: The `max_steps_a11y` and `max_steps_vision` defaults have been tightened to `4` steps to enforce fast failure and rapid orchestration-level fallback.
