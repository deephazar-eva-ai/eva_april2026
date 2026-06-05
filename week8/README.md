# Agentic Orchestrator (Week 8)

This project implements a robust Agentic Orchestrator for executing Directed Acyclic Graph (DAG) based queries using various LLMs and specialized skills (e.g., Researcher, Formatter, Coder, Translator).

## Key Features

1. **Intelligent LLM Gateway (V8)**: 
   - A central gateway that routes requests to different LLM providers (Gemini, Groq, OpenRouter, etc.).
   - Manages rate-limits seamlessly.
   - Provides an intelligent wait and backoff mechanism for provider-specific transient errors (`429`, `503`) and cooldown states.
   - Supports "agent pinning" to bind a specific model to an agent, with fallback mechanisms to ensure graceful degradation.

2. **Orchestrator & DAG Execution**:
   - Complex user queries are broken down into a DAG by a Planner node.
   - Nodes execute in parallel, querying multiple LLM providers concurrently.
   - Formatter nodes synthesize branch outputs into a final coherent response.
   - Critic nodes review output and enforce constraints (e.g., producing both pass and fail on certain checks) to guarantee high-quality execution.

3. **Productive Failure Recovery**:
   - The Orchestrator intercepts transient errors from the gateway. 
   - Instead of immediately abandoning failed branches, it triggers a "replan" and queues the node for recovery. 
   - Together with the gateway's wait logic, this avoids infinite failure loops and seamlessly repairs broken branches.

## Execution Log

To see an end-to-end trace of queries being executed by the Orchestrator, view the attached log file:
[testquery_log.txt](./testquery_log.txt)

This log demonstrates:
- Parallel execution of multiple web-searches and data-extraction runs.
- Graceful error recovery during provider rate-limit congestion.
- Synthesis of structured tables, coding logic, and text-based reasoning across different tools.
