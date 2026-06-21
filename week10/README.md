# Week 10 — Headless Desktop Agent with Vision-Guided Automation

A multi-skill AI agent running inside a headless Docker container, capable of
desktop GUI automation, web browsing, programmatic file manipulation, and
vision-guided image editing. Built on a growing-graph orchestrator that
decomposes user queries into parallel skill nodes.

---

## Test Queries and Trajectories

Here are examples of completed sessions and their recorded trajectories:

**Query 1 (LibreOffice GUI & Fallback):**
> "Open the spreadsheet /home/acer/Documents/DEEPAK/eva_april2026/mainbranch/eva_april2026/week10/data/tasklist.ods . Find all rows where Status is \"Pending\" and Due Date is earlier than today. Create a new sheet named 'Overdue' containing those rows sorted by Due Date."

[Trajectory Folder: s8-a3e08472](https://github.com/deephazar-eva-ai/eva_april2026/tree/main/week10/queryrecording/s8-a3e08472)

**Query 2 (GNOME Calculator GUI):**
> "add 45 and 98 and fetch the result"

[Trajectory Folder: s8-f7487724](https://github.com/deephazar-eva-ai/eva_april2026/tree/main/week10/queryrecording/s8-f7487724)

**Query 3 (Electron CDP & DOM Parsing):**
> "Open the currently active VS Code workspace. Find all comments in Python files and create a new file in data folder named python_comments_summary.md containing the filename and comments text grouped by file."

[Trajectory Folder: s8-c12076f0](https://github.com/deephazar-eva-ai/eva_april2026/tree/main/week10/queryrecording/s8-c12076f0)

---

## Architecture: Five Layers

The system is organised into five layers, each adding a distinct capability
and escalation path:

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1 — Static Extraction (trafilatura, no LLM)          │
│  Pure HTTP GET → HTML → trafilatura text extract             │
├─────────────────────────────────────────────────────────────┤
│  Layer 2a — Deterministic Selectors (Playwright, no LLM)    │
│  Caller-supplied CSS selectors → click/fill/key actions      │
├─────────────────────────────────────────────────────────────┤
│  Layer 2b — Accessibility (A11y) Driver (text-only LLM)     │
│  AT-SPI / DOM legend → /v1/chat → action JSON               │
├─────────────────────────────────────────────────────────────┤
│  Layer 3 — Set-of-Marks Vision Driver (vision LLM)          │
│  Screenshot + Pillow annotations → /v1/vision → action JSON  │
├─────────────────────────────────────────────────────────────┤
│  Layer 5 — Vision Fallback (emergency escalation)           │
│  Raw screenshot → /v1/vision for coordinate detection        │
└─────────────────────────────────────────────────────────────┘
```

### Layer 1 — Static Extraction
- Fires first on every browser skill invocation
- Plain `httpx.AsyncClient` GET, then `trafilatura.extract()` for content
- Gateway-block detection (CAPTCHA, Cloudflare, login walls) checks the HTML
  for known markers *before* wasting LLM tokens
- If extraction is sufficient (evaluated by a lightweight LLM call), the
  cascade stops here — no browser launch needed

### Layer 2a — Deterministic Selectors
- Optional escape hatch when the caller supplies `metadata.selectors`
- Playwright executes a sequence of `{action, selector, value}` steps
- Used for known, stable UI paths (e.g., filling a login form with known
  CSS selectors)

### Layer 2b — A11y Driver (Text-Only)
- Playwright renders the page, then `dom.enumerate_interactives()` walks the
  accessibility tree and assigns integer IDs to every interactive element
- A text legend (`[id]<tag role="role">name</tag>`) is sent to the LLM
  gateway `/v1/chat` (no screenshot — cheaper)
- The LLM returns a structured `{thinking, actions}` JSON matching
  `ACTION_SCHEMA`
- Actions are dispatched via Playwright: `click(mark)`, `type(mark, value)`,
  `key(value)`, `scroll(direction)`, `drag(from, to)`, `done(success)`
- Multi-step loop with `max_steps_a11y` (default 4) and failure cap

### Layer 3 — Set-of-Marks Vision
- Same element enumeration as Layer 2b, but now the screenshot is annotated
  with **dashed numbered bounding boxes** over each interactive element
  (via `highlight.py` / Pillow)
- Annotated screenshot + text legend → `/v1/vision` call
- The VLM can see the actual page rendering (buttons, images, layouts) and
  use the numbered marks to reference elements precisely
- Escalation trigger: Layer 2b output was empty or evidently insufficient

### Layer 5 — Vision Fallback (Desktop Agent)
- Emergency escalation inside `mcp_runner.py` when the desktop agent
  (`computer` skill) encounters 3+ consecutive errors
- Sends the raw `cua-driver` screenshot to `/v1/vision` for coordinate
  detection
- Used when the AT-SPI accessibility tree is blind (e.g., `elements=1`
  for LibreOffice)

---

## Cascade Decision Logic

The browser skill (`browser/skill.py`) owns the escalation cascade:

```
      User request
           │
    ┌──────▼──────┐
    │  Layer 1    │─── sufficient? ──→ return
    │  (extract)  │        │
    └──────┬──────┘        no
           │
    ┌──────▼──────┐
    │  Layer 2a   │─── selectors given? ──→ try → success? → return
    │  (determ.)  │        │
    └──────┬──────┘       no / fail
           │
    ┌──────▼──────┐
    │  Layer 2b   │─── success? ──→ return
    │  (a11y)     │        │
    └──────┬──────┘       no
           │
    ┌──────▼──────┐
    │  Layer 3    │─── success? ──→ return
    │  (vision)   │        │
    └──────┴──────┘       no
           │
    "all layers exhausted" error
```

**Gateway-block short circuit:** If Layer 1's HTML contains CAPTCHA /
Cloudflare / login-wall markers, the skill returns immediately with
`error_code="gateway_blocked"` — no Playwright launch, no wasted LLM
calls.

**Sufficiency evaluation:** Layer 1 content is judged by a lightweight LLM
call (`_evaluate_extract`). Interactive verbs in the goal (click, fill,
submit) automatically trigger escalation to Layer 2b regardless of content
length.

**Force path:** Callers can set `metadata.force_path = "vision"` to skip
straight to Layer 3 (used in smoke tests).

---

## Orchestrator & Skill System

### Growing-Graph Executor (`flow.py`)

The orchestrator is a NetworkX DiGraph where each node is a skill invocation.
The graph **grows at runtime** via five actors:

1. **Planner seed plan** — initial DAG decomposition of the user query
2. **Dynamic successors** — any skill can emit `result.successors` to add
   new nodes
3. **Static internal_successors** — `coder` always chains to
   `sandbox_executor` (declared in `agent_config.yaml`)
4. **Critic auto-insertion** — skills with `critic: true` get a Critic node
   gated on every outgoing edge
5. **Recovery re-planning** — on node failure, a new Planner node is queued
   with the failure report and prior successful results

### Skills Catalogue

| Skill | Role | Tools |
|-------|------|-------|
| `planner` | Decomposes queries into DAG; recovery re-planning | — |
| `coder` | Emits Python code in `{"code", "rationale"}` | — |
| `sandbox_executor` | Runs coder's Python in a subprocess sandbox | — |
| `computer` | Desktop automation via cua-driver (AT-SPI) | get_accessibility_tree, desktop_judgment, launch_app, etc. |
| `browser` | Four-layer web cascade (extract → a11y → vision) | — |
| `researcher` | Web research (deprecated → use browser) | web_search, fetch_url |
| `retriever` | FAISS-indexed knowledge base search | search_knowledge |
| `distiller` | Extracts structured fields from raw text | — |
| `summariser` | Condenses long content | — |
| `critic` | Pass/fail evaluation of upstream output | — |
| `formatter` | Renders the final user-facing answer (terminal) | — |

### Custom MCP Tools (injected in `mcp_runner.py`)

| Tool | Purpose |
|------|---------|
| `edit_image` | Vision-guided image editing via Pillow + V9Client vision |
| `modify_spreadsheet` | Programmatic ODS manipulation via ezodf |

---

## Three Tasks

### Task 1: Spreadsheet Automation — "Overdue" Sheet Creation

**Query:** Filter overdue tasks from `v1_tasklist.ods`, create a new
"Overdue" sheet, paste filtered rows, sort by due date.

**Routing:** Planner → `computer` skill → LibreOffice Calc via cua-driver

**Cascade decisions:**
- Desktop agent uses scan-act-verify loop (Layer 2b equivalent for AT-SPI)
- LibreOffice keyboard shortcuts (`alt+s i enter` for sheet insert,
  `ctrl+s` for save) bypass the unreliable element clicking
- When cua-driver reports `elements=1` (AT-SPI blindness), the agent falls
  back to the `modify_spreadsheet` MCP tool (ezodf)

**Failure modes encountered:**
- **Hop exhaustion** (Run 1): Agent stuck in filter dialog, used 120/120
  hops without saving. Fix: increased to 200 hops + emergency forced save
- **AT-SPI blindness** (Run 2): `cua-driver` v0.5.7 only sees the window
  frame (`elements=1`), not LibreOffice internal widgets. Fix:
  `modify_spreadsheet` programmatic fallback
- **Agent detected blindness** (Run 3): Blind window warning triggered
  correctly, agent saved and exited early. File unchanged because GUI
  actions were still blind
- **Save-before-kill violation** (Trap 8): Agent called `kill_app` without
  executing `ctrl+s`. Fix: `save_verified` guard in `mcp_runner.py`

### Task 2: Image Editing — "Draw on Image"

**Query:** Open an image, identify objects (e.g., black rectangle), draw
annotations (e.g., red circle above it).

**Routing:** Planner → `computer` skill → `edit_image` MCP tool

**Cascade decisions:**
- `edit_image` with `query` parameter triggers the browser skill's V9Client
  vision pipeline (`/v1/vision` — same endpoint as Set-of-Marks Layer 3)
- Vision model analyzes the image, identifies object bounding boxes, returns
  structured JSON with drawing operations
- Pillow executes the operations (draw_circle, draw_rectangle, draw_line,
  draw_text) and saves the file

**Failure modes encountered:**
- **GUI editor loops** (GIMP/KolourPaint): Agent tried to launch non-existent
  image editors 20+ times. Fix: infinite loop guard (4 identical calls or
  8 total calls to `launch_app`)
- **`UnboundLocalError: json`**: Local `import json` inside `run_with_tools`
  shadowed the module-level import — Python treated `json` as local
  throughout the entire function. Fix: hoisted all 15 local imports to module
  level
- **Sync/async mismatch**: `LLM().vision()` is synchronous but was called
  with `await`. Fix: replaced with async `V9Client.vision()`

### Task 3: File Operations — "Extract Python Comments"

**Query:** Find all comments in Python files in the workspace, create
`python_comments_summary.md`.

**Routing:** Planner → `computer` skill → Cursor (Electron) via `page` tool

**Cascade decisions:**
- Planner routes exclusively to the `computer` skill, forbidding the `coder` fallback, enforcing an end-to-end GUI-driven extraction.
- The agent launches Cursor with `--remote-debugging-port=9222`, connecting via the `page` tool to evaluate Chrome DevTools Protocol (CDP) scripts.
- Agent uses `ctrl+shift+f` to search, reads the DOM precisely, and uses the integrated terminal (`ctrl+\``) to bypass unreliable native save dialogs.

**Failure modes encountered:**
- **CDP Port Routing Failure** (Phase 1): The agent passed raw strings to `launch_app`, bypassing the multiplexer. The `page` tool attached to the wrong PID. Fix: intercept logic in `mcp_runner.py` to route debug ports correctly.
- **Node Integration Missing** (Phase 2): Agent tried to evaluate `require('fs')` in the browser context, crashing due to `contextIsolation: true`. Fix: Trap 11 added, enforcing GUI-only search.
- **Ghost Process Blocking CDP** (Phase 4): Cursor was already running in the background. Subsequent launches opened new windows but failed to bind the debug port. Fix: Explicit `killall -9 cursor` before launching.
- **Blind DOM Hallucination & GTK Save Bug** (Phase 5): The agent dumped `document.body.innerText`, hallucinated fake results, and then lost focus in the GTK save dialog, creating an accidental `.yaml` file. Fix: Precise DOM extraction payload (`Array.from(...)`) and terminal-based file echoing.
---

## Failure Modes & Guards

### Import Shadowing (`UnboundLocalError`)

Python treats a name as **local throughout an entire function** if that name
is imported/assigned *anywhere* in the function — even inside an unexecuted
conditional branch. The `run_with_tools` function had 15 scattered `import`
statements (`time`, `subprocess`, `platform`, `glob`, `copy`) inside `if`
blocks. Any reference to these names before the import branch was reached
caused `UnboundLocalError`.

**Fix:** All 15 local imports hoisted to module level.

### Infinite Tool Call Loops

The agent enters loops when a tool consistently fails but the LLM keeps
retrying with slightly different arguments.

**Guard (two levels in `mcp_runner.py`):**

| Level | Detection | Threshold | Example |
|-------|-----------|-----------|---------|
| 1 | Exact match (tool + args) | 4 consecutive | `launch_app("gimp")` × 4 |
| 2 | Counter per tool name | 8 total calls | `launch_app` with varying flags |

### Scan-Act-Verify Protocol

Every desktop automation turn must follow three phases:
1. **Scan:** `get_window_state` to build element cache
2. **Act:** `desktop_judgment` with element_index or keyboard action
3. **Verify:** `get_window_state` again to confirm the action worked

Violations are logged to trajectory turn folders for debugging.

### Save-Before-Kill Guard (Trap 8)

The `save_verified` flag blocks `kill_app` until `ctrl+s` has been executed
and verified by a subsequent scan. If the agent exhausts all hops without
saving, an emergency forced save fires via `xdotool key ctrl+s`.

### Recovery Policy (`recovery.py`)

| Failure Class | Action | Rationale |
|---------------|--------|-----------|
| Transient (503/502/timeout) | Skip | Gateway already retried internally |
| Validation error | Skip | Prompt bug, not runtime recoverable |
| Planner failure | Skip | Would loop on planner errors |
| Upstream failure | Replan | Queue recovery Planner with failure report |
| Critic fail (1st) | Replan | Re-plan the failing branch with new approach |
| Critic fail (2nd+) | Skip + cap | Branch skipped; final answer flags missing data |

---

## Docker Environment

### Container Layout

```
/app/
├── code/                  # Agent source (skills, prompts, drivers)
│   ├── browser/           # Browser skill (4-layer cascade)
│   ├── prompts/           # Skill prompt templates
│   ├── flow.py            # Growing-graph orchestrator
│   ├── mcp_runner.py      # Tool-use loop + custom MCP tools
│   ├── skills.py          # Skill registry + prompt rendering
│   ├── recovery.py        # Failure classification + recovery
│   └── agent_config.yaml  # Skill catalogue
├── llm_gatewayV9/         # LLM gateway (V9, port 8109)
├── entrypoint.sh          # Xvfb + D-Bus + AT-SPI + openbox setup
└── .env                   # API keys
```

### Bind Mounts (from `run_in_docker.sh`)

| Host | Container | Purpose |
|------|-----------|---------|
| `week10/data` | Same host path | Spreadsheets, images, output files |
| `week10/trajectories` | `/app/trajectories` | Session recordings |
| `week10/code` | `/app/code` | Live code reload |

### Installed Software

| Available | Not Available |
|-----------|---------------|
| LibreOffice Calc (GTK3) | VS Code |
| GNOME Calculator | Chrome / Firefox |
| xdotool, wmctrl | GIMP / KolourPaint |
| Python 3.12, Pillow, ezodf | |
| Playwright (headless Chromium) | |
| cua-driver v0.5.7 | |

### Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `DISPLAY` | `:99` | Xvfb virtual framebuffer |
| `SAL_USE_VCLPLUGIN` | `gtk3` | LibreOffice AT-SPI bridge |
| `GDK_BACKEND` | `x11` | GTK backend for Xvfb |
| `GNOME_ACCESSIBILITY` | `1` | Enable AT-SPI globally |

---

## Running

```bash
# Start the LLM gateway (host side, keep running)
cd llm_gatewayV9 && ./run.sh

# Run a task in Docker
./run_in_docker.sh "Open LibreOffice Calc with v1_tasklist.ods and create an Overdue sheet"

# Resume a failed session
./run_in_docker.sh --resume s8-abc12345 "Continue the task"
```

---

## Key Files

| File | Purpose |
|------|---------|
| `code/flow.py` | Growing-graph orchestrator (NetworkX DAG) |
| `code/skills.py` | Skill registry, prompt rendering, environment context |
| `code/mcp_runner.py` | Tool-use loop, loop guards, custom MCP tools |
| `code/recovery.py` | Failure classification and recovery decisions |
| `code/agent_config.yaml` | Skill catalogue (prompts, tools, routing) |
| `code/browser/skill.py` | Browser 4-layer cascade |
| `code/browser/driver.py` | A11y + Set-of-Marks drivers |
| `code/browser/highlight.py` | Pillow-based screenshot annotation |
| `code/prompts/planner.md` | Planner system prompt with routing rules |
| `code/prompts/computer.md` | Desktop agent prompt (scan-act-verify) |
| `code/prompts/coder.md` | Code generation prompt |
| `bugfix/` | Detailed bugfix chronicles (see below) |

---

## Bugfix Chronicle

All failure investigations are documented in the `bugfix/` folder. Each file
traces a specific failure class from symptom through root cause to fix.

| File | Failure | Root Cause |
|------|---------|------------|
| [fix_hops_burn_savefile.md](bugfix/fix_hops_burn_savefile.md) | Agent exhausted 120 hops, AT-SPI blindness (`elements=1`), `UnboundLocalError` crashes, infinite `launch_app` loops, missing environment context | 17 updates covering hop exhaustion → blind window → programmatic fallback → import shadowing → loop guards → vision integration → Docker context injection |
| [hallucinating_bug.md](bugfix/hallucinating_bug.md) | Agent hallucinated task completion — reported "Overdue sheet created" but never actually renamed the sheet, never sorted data, navigated filter menus blindly | Agent used `down down down enter` in transient dropdowns without verification; replaced with explicit Standard Filter SOP (`alt+d f s`) with exact tab sequences |
| [key_mapping_bug.md](bugfix/key_mapping_bug.md) | Agent mixed `type_text` with keystrokes — literally typed "Overdue enter" as text; used obsolete LibreOffice shortcuts (`shift+f11`, `alt+o s r`) causing data corruption | Separated `type_text` from `hotkey` tool calls; updated to modern LO 7.x accelerators (`alt+s i enter`, `alt+s r`) |
| [outputfile_locked_bug.md](bugfix/outputfile_locked_bug.md) | LibreOffice lock files blocked subsequent runs; `xdotool` rejected `end`/`page down` keys; agent killed app before save flushed to disk | Pre-run lock file cleanup, key name mapping (`page down` → `Page_Down`), 2s disk-flush delay before `kill_app`, Trap 8 save-verification guard |
| [tool_calls_mutation_bug.md](bugfix/tool_calls_mutation_bug.md) | Agent stuck in infinite `desktop_judgment` loop with malformed args (`{"key": "f"}` instead of proper schema) | `mcp_runner.py` mutated `tool_calls` in-place — LLM's conversation history saw mutated args and mimicked them; fixed with `copy.deepcopy()`. Also fixed `xdotool` sequence timing (0.3s delay between menu keystrokes) |

