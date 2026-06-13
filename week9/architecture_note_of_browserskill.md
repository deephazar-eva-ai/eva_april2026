# Week 9 Project Architecture Note

The Week 9 project represents an advanced agentic orchestration system designed for multi-step research, reasoning, and autonomous browser execution. The architecture is built around a dynamically growing Directed Acyclic Graph (DAG) that coordinates specialized cognitive skills (Planner, Researcher, Distiller, Critic, Formatter, and a multi-layered Browser) through a unified LLM Gateway.

## Core Architectural Components

### 1. Orchestrator (`flow.py`)
The orchestrator is the heart of the system, transforming the execution loop into a dynamically growing NetworkX `DiGraph`.
- **Growing Graph:** Unlike static workflows, the DAG expands at runtime. The `Planner` seeds the graph, and the orchestrator dynamically splices in new nodes (e.g., dynamically spawned browser tasks, automatic critics, or recovery planners).
- **Concurrent Execution:** Uses `asyncio` to execute independent DAG branches in parallel, respecting data dependencies.
- **Critic Auto-Insertion:** If a skill is configured as `critic: true` (like the Distiller), the orchestrator automatically splices a Critic node into its outgoing edges to validate the output before it reaches the Formatter.

### 2. Failure Recovery System (`recovery.py`)
A highly resilient exception-driven recovery system that classifies failures and adjusts the DAG without crashing the session.
- **Classification (`classify_failure`):** Distinguishes between `transient` (Gateway timeouts), `validation_error` (malformed JSON), and `upstream_failure` (genuine task roadblocks).
- **Critic Failures (`handle_critic_verdict`):** If a Critic rejects a node's output (e.g., hallucinated data), the orchestrator triggers a recovery Planner. 
- **Amnesia Fix:** During recovery, the orchestrator explicitly feeds the IDs of *previously successful nodes* into the recovery Planner's context. This prevents the Planner from starting from scratch and ensures it only replans the failed branches using alternate approaches (e.g., switching URLs).

### 3. Browser Skill Cascade (`browser/skill.py`, `browser/driver.py`)
The Browser skill is a fully autonomous, four-layer escalation cascade designed to fetch web content reliably.
- **Layer 1 (Extract):** Pure HTTP extraction using `trafilatura`. Extremely fast, no LLM required.
- **Layer 2a (Deterministic):** Executes exact Playwright selectors (clicks/fills) if explicitly provided by the Planner.
- **Layer 2b (A11y):** Uses the Accessibility (A11y) tree and the `gemini` LLM to interact with DOM elements (scroll, click, type) textually.
- **Layer 3 (Vision):** Uses a `Set-of-Marks` (SoM) approach with a Vision LLM (`v1/vision`) to visually identify and click elements when the DOM is obscured (e.g., Canvas).
- **Gateway Block Detection:** Proactively detects CAPTCHAs, Cloudflare interstitials, and "Access Denied" walls. It raises a fatal error immediately, forcing the orchestrator to replan with alternate URLs instead of wasting LLM tokens on blocked pages.

### 4. LLM Gateway (`llm_gatewayV9/`)
A centralized routing and failover service that abstracts the underlying LLM providers from the orchestrator.
- **Agent-Based Routing:** Routes requests based on the cognitive role (`agent=planner`, `agent=browser`, etc.) utilizing `agent_routing.yaml`.
- **Failover & Cooldowns:** If a model (e.g., Ollama `gemma4:31b`) returns a 503 or 404, the Gateway seamlessly fails over to fallback candidates while placing the failing provider on a temporary cooldown.
- **Cost Tracking:** Maintains a SQLite ledger (`gateway_v8.db`) attributing token usage and costs directly to specific DAG sessions.

### 5. Memory & RAG (`memory.py`, `vector_index.py`)
Persistent, cross-session memory leveraging FAISS.
- Records user queries, extracted facts, and session outcomes.
- At the start of a session, `flow.py` queries the FAISS index and injects the top `MEMORY HITS` into every skill's prompt, allowing the agent to utilize past research without re-fetching it.

### 6. Skills & Tool Access (`skills.py`, `mcp_server.py`)
- **Skill Registry:** Loads skill constraints (temperature, tokens, allowed tools) from `agent_config.yaml`.
- **Input Resolution:** Translates DAG node IDs (e.g., `n:3`) into concrete JSON payloads for downstream prompts.
- **MCP Integration:** Exposes tools (`web_search`, `fetch_url`, `search_knowledge`) to specific skills (like the `Researcher`) via the Model Context Protocol, enabling multi-turn tool-use loops.

## Data Flow Example
1. **User Query:** "Compare 3 laptops under ₹80,000."
2. **Planner:** Emits 3 parallel `browser` nodes with distinct search engine URLs.
3. **Browser Cascade:** Attempts extraction. If a URL is blocked, it halts early. If it requires scrolling, it escalates to the A11y driver.
4. **Distiller:** Extracts structured specs (Processor, RAM, Price) from the raw browser text.
5. **Critic (Auto):** Validates that the Distiller actually extracted 3 laptops. If it only found 1, the Critic fails the node.
6. **Recovery:** The Orchestrator spawns a recovery Planner, feeding it the successful nodes and instructing it to try a new URL (e.g., an e-commerce site) for the missing data.
7. **Formatter:** Compiles the successfully distilled records into a clean Markdown table for the user.
