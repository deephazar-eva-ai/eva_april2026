# Week 8 Project Summary: Agentic Orchestrator & LLM Gateway

The Week 8 project implements a highly robust, fault-tolerant **Agentic Orchestrator** backed by an **Intelligent LLM Gateway**. It processes complex user queries by breaking them down into Directed Acyclic Graphs (DAGs) and executing them in parallel across multiple LLMs using specialized "skills."

## Core Architecture

### 1. The Agentic Orchestrator (`code/flow.py`)
The Orchestrator delegates work to a network of specialized agents:
- **Planner**: Deconstructs the query into a DAG of sub-tasks.
- **Researcher**: Executes web searches and scrapes data via the MCP server.
- **Coder**: Writes and executes Python code in an isolated sandbox.
- **Critic**: Evaluates output to enforce quality constraints.
- **Formatter**: Synthesizes completed branch results into a final response.

### 2. The LLM Gateway V8 (`gateway/main.py`)
A central API gateway sits between the orchestrator and upstream LLMs (Gemini, Groq, OpenRouter) to manage heavy parallel loads:
- **Rate Limit Management**: Tracks RPM and RPD quotas per provider.
- **Intelligent Wait Mechanisms**: Calculates the exact time remaining until a quota refreshes, dynamically pausing execution instead of failing aggressively on rate limits (e.g., `429`).
- **Provider Failover**: Automatically falls back to secondary LLMs during outages.
- **Agent Pinning**: Binds specific skills to preferred models.

### 3. Failure Recovery (`code/recovery.py`)
To handle API and network instability, the system uses a **Productive Re-planning** strategy. If a sub-task fails due to a transient error, the orchestrator dynamically splices a new Planner node into the DAG for recovery. Combined with the gateway's wait logic, this prevents infinite failure loops and enables self-healing.

### 4. MCP Server Integration (`tools/mcp_server.py`)
Tool execution is decoupled using the Model Context Protocol, protecting the main orchestrator from runtime crashes or malformed LLM outputs.

## Conclusion
By decoupling planning, execution, and validation—and backing it with a resilient LLM gateway—this asynchronous orchestrator reliably solves multi-step, research-intensive tasks.
