# Financial IRR Modeling & Floating Rate Simulation Agent

This project implements an autonomous financial modeling agent capable of calculating fixed-rate loan IRRs and performing sophisticated Monte Carlo simulations for floating-rate risk analysis. 

The architecture consists of two primary components: an **LLM Orchestrator Agent** and an **MCP (Model Context Protocol) Tool Server**.

## Project Components

### 1. `agent6.py` (LLM Orchestrator)
The orchestrator script uses `asyncio` to manage interactions between the LLM and the MCP server. It executes a comprehensive financial modeling workflow autonomously.

**Key Features:**
- **Sequential Execution Loop**: Forces the LLM to execute tools in a deterministic order (fixed-rate calculation first, followed by the Monte Carlo simulation).
- **Prompt Engineering**: The `SYSTEM_PROMPT` is strictly defined to prevent human-in-the-loop pauses and ensures the LLM returns the expected `Fixed-Rate Annualized IRR` as its final numeric answer.
- **Verification Engine**: Parses the LLM's final response and tool execution traces into a Pydantic `Verdict` model. It extracts both the fixed-rate verification check and the Monte Carlo summary statistics.
- **Pretty Formatting**: Prints the final report along with dynamic JSON/string formatting and ASCII histogram visualizations of the IRR distribution.

### 2. `mcp_server.py` (FastMCP Server)
The backend service providing mathematical and financial modeling tools via the FastMCP protocol using JSON-RPC over standard input/output.

**Key Tools:**
- `calculate_irr_with_upfront`: Derives the effective fixed-rate IRR of an EMI-based loan, accounting for upfront processing fees/deductions.
- `monte_carlo_floating_irr`: Runs thousands of stochastic interest-rate paths based on market volatility (Geometric Brownian Motion or Vasicek models) to estimate tail-risk, yield volatility, and IRR percentiles (P5, P95). It additionally generates a visual ASCII histogram of the simulated IRR distribution.
- Other auxiliary math and basic floating-rate deterministic simulation tools.

## Execution Workflow

When `uv run agent6.py` is executed, the agent:
1. Receives loan parameters (Principal: ₹100k, EMI: ₹1,020, Tenure: 120M, Upfront Deduction: 5%).
2. Calls `calculate_irr_with_upfront` to determine the true cost of borrowing (`5.39454%` Annualized IRR).
3. Uses the output as the `initial_rate` to call `monte_carlo_floating_irr`.
4. Synthesizes a comprehensive financial analysis report explaining APR vs. IRR, yield enhancement, ALM implications, and floating-rate tail risks.
5. Verifies the output and prints the Monte Carlo distribution ASCII chart to the terminal.

## Dependencies
- `mcp`: To handle FastMCP protocol communications.
- `pydantic`: For structured LLM verification outputs and agent tracing.
- `numpy` & `numpy-financial`: For vectorized financial derivations and IRR solving.
- `scipy`: For stochastic random variable generation.

## Usage
Run the agent script directly. Ensure your LLM Gateway (`llm_gatewayV3`) is active on the configured port.
```bash
uv run agent6.py
```
