# Agent6 Orchestrator Code Summary

This document summarizes the architecture and logic of the `week6_assgnmt` Agent6 Python codebase. Agent6 is a Directed Acyclic Graph (DAG) LLM orchestrator built to achieve complex tasks rapidly with strict iteration limits and stable environment execution.

## Core Modules

### 1. `main.py`
The entry point of the application. 
- **Setup:** Initializes the `mcp_session_manager`, which manages the Model Context Protocol (MCP) server lifecycle for secure tool execution.
- **GatewayAdapter:** Wraps the `LLM` client instance with robust error handling, implementing automatic retries for `502 Bad Gateway`, `503 Service Unavailable`, and `504 Gateway Timeout` errors to handle high-concurrency requests safely.
- **REPL Loop:** Runs the interactive command-line interface.

### 2. `core/orchestrator.py`
The brain of the agent, containing the `Agent6Orchestrator` class.
- Manages the central loop: `Memory -> Perception -> Decision -> Action`.
- Executes open goals in parallel using `asyncio.gather`.
- Employs strict programmatic constraints (e.g., stripping the `mcp_tools` payload from goals that have already made a tool call) to mechanically guarantee that goals conclude within 2 iterations (preventing infinite search loops).

### 3. `core/perception.py`
The planner layer.
- Uses the LLM to decompose a user's query into an actionable array of `Goal` objects.
- **Goal Consolidation:** Specifically prompted to combine independent information-gathering tasks into a single goal to minimize execution overhead.
- **DAG Artifact Inheritance:** Intelligently maps memory hits to goals. If a child goal depends on a parent goal, it automatically inherits the parent's generated artifact payload, allowing data to flow down the DAG seamlessly.

### 4. `core/decision.py`
The execution decider layer.
- Evaluates an individual open goal using its attached artifact payload and recent memory history.
- **Prompt Scrubbing:** Uses regex to scrub internal memory handles (`art:xyz`) from the prompt to prevent the LLM from hallucinating tools to fetch internal states.
- **Iteration Caps:** Heavily prompted to degrade gracefully and output a final `ANSWER` immediately if proxy data is available, rather than repeatedly calling `web_search` for overly specific facts.

### 5. `core/action.py`
The MCP tool dispatcher.
- Receives tool calls formatted by the Decision layer.
- Validates that the LLM is not attempting to pass internal `art:` handles as tool arguments.
- Executes the tool via the MCP protocol and stores the raw results in the `ArtifactStore`.

### 6. `core/memory.py`
The short-term memory engine.
- Logs all user queries and tool outcomes as `MemoryItem` events.
- Employs a semantic keyword overlap system to surface relevant past actions when the Orchestrator requests context for a new goal.

### 7. `core/artifacts.py`
The content-addressable storage layer.
- Solves the problem of LLM context bloat.
- When an action returns a large payload (like a 64KB scraped Wikipedia page), it stores the raw bytes in `ArtifactStore` and returns a compact hash handle (e.g., `art:a5444f835433`). 
- Only the specific goal that needs the data will have the full artifact attached to its prompt.

### 8. `core/models.py` & `core/schemas.py`
- Contains the Pydantic classes that define the structured JSON responses mandated by the Gateway layer, such as the `Goal` schema with its DAG `depends_on` array.
