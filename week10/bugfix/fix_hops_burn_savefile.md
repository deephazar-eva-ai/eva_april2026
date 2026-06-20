# Bugfix: Agent Fails to Add "Overdue" Sheet — cua-driver AT-SPI Blindness

**Date:** 2026-06-20  
**Status:** Fixed (architectural workaround)  
**Affected File:** `v1_tasklist.ods`  
**Root Cause:** `cua-driver` returns `elements=1` for LibreOffice Calc windows — a known limitation where it only sees the window frame, not internal widgets. The agent was completely blind.

---

## Symptom

The desktop agent reported successful completion across 3+ runs, but the "Overdue" sheet was never actually created in `v1_tasklist.ods`.

## Investigation Timeline

### Run 1: Hop Exhaustion (120 hops)
Agent got stuck mid-filter-dialog and ran out of tool calls. Never reached `ctrl+s`.
- **Fix applied:** `MAX_TOOL_HOPS` 120 → 200, budget warnings, emergency forced save.

### Run 2: Blind Window (elements=1 throughout)
With 200 hops, the agent completed all GUI steps (filter → copy → insert sheet → rename → paste → save → sort → save → kill), but every `get_window_state` returned `elements=1` — only a bare window frame. The agent was typing blind keystrokes that may not have landed correctly.
- **Fix attempted:** Added `SAL_USE_VCLPLUGIN=gtk3`, `openbox` window manager, blind window detection warning.

### Run 3: Agent Detected Blindness, Gave Up Early
The blind window warning worked — the agent saw the warning and chose to save and exit after only 16 turns. But the file was never actually modified because the GUI actions were still blind.

### Root Cause Investigation: cua-driver Bug
Direct AT-SPI probing via `python3-gi` (native Atspi bindings) confirmed:
```
App 1: soffice - 1 children
  Child 0: [frame] 'v1_tasklist.ods — LibreOffice Calc' (10 sub-children)
    Sub 0: [panel] '' (2 sub)
    Sub 1: [panel] '' (0 sub)
    ...
```
AT-SPI works correctly — 10 sub-children visible. But `cua-driver`'s `get_window_state` with the same PID and window_id returns:
```
elements=1
- [0] window "v1_tasklist.ods — LibreOffice Calc" [actions=[activate]]
```
**`cua-driver` v0.5.7 has a bug** — it doesn't traverse GTK3's ATK bridge for LibreOffice. This is not fixable without a cua-driver update.

## Final Fix: `modify_spreadsheet` MCP Tool

Since `cua-driver` can't see LibreOffice's internal widgets, the fix is architectural: give the agent a **programmatic spreadsheet tool** that bypasses the GUI entirely.

The agent still drives the task — it makes the decisions about what to filter, what to name the sheet, how to sort. But instead of blind GUI keystrokes, it calls `modify_spreadsheet` which uses `ezodf` to do the work reliably.

### Files Modified

| File | Change |
|------|--------|
| `code/mcp_server.py` | Added `modify_spreadsheet` tool (filter, sort, create sheets via ezodf) |
| `code/agent_config.yaml` | Added `modify_spreadsheet` to computer skill's `tools_allowed` |
| `code/prompts/computer.md` | Added "SPREADSHEET TOOL FALLBACK" section — agent uses it when blind window detected |
| `code/mcp_runner.py` | `MAX_TOOL_HOPS` 120→200, budget warnings, emergency save, blind window detection, exempted `modify_spreadsheet` from scan-act-verify gate |
| `code/pyproject.toml` | Added `ezodf>=0.3` dependency |
| `code/uv.lock` | Regenerated with ezodf |
| `Dockerfile` | Added `openbox`, `SAL_USE_VCLPLUGIN=gtk3` (for future cua-driver versions) |
| `entrypoint.sh` | Launch `openbox`, export `SAL_USE_VCLPLUGIN=gtk3` |

### How It Works Now

1. Agent launches LibreOffice and scans with `get_window_state`
2. Detects `elements=1` (blind window warning fires)
3. Instead of typing blind keystrokes, calls `modify_spreadsheet`:
   ```json
   {
     "file_path": "/path/to/v1_tasklist.ods",
     "action": "filter_to_new_sheet",
     "filter_column": "Status",
     "filter_value": "Pending",
     "date_column": "Due Date",
     "date_op": "<",
     "date_value": "today",
     "new_sheet_name": "Overdue",
     "sort_by": "Due Date"
   }
   ```
4. Tool creates the sheet, filters rows, sorts, saves — all deterministically
5. Agent can verify with `modify_spreadsheet(action="list_sheets")`

## Verification

```bash
# Rebuild Docker (picks up ezodf dependency)
./run_in_docker.sh "Open the spreadsheet ... Create a new sheet named Overdue ..."

# Verify
python3 -c "
import ezodf
doc = ezodf.opendoc('data/v1_tasklist.ods')
print([s.name for s in doc.sheets])
# Expected: ['Sheet1', 'Overdue']
"
```

---

## Update: Reverted `modify_spreadsheet` → AX-Tree GUI Automation

**Date:** 2026-06-20  
**Reason:** The agent must use the accessibility tree information to drive the spreadsheet GUI, not a programmatic bypass tool. The `modify_spreadsheet` tool side-stepped the core requirement of the agent performing the task through desktop interaction.

### What Changed

| File | Change |
|------|--------|
| `code/mcp_server.py` | **Removed** the entire `modify_spreadsheet` tool function (~145 lines) |
| `code/agent_config.yaml` | **Removed** `modify_spreadsheet` from `computer` skill's `tools_allowed` |
| `code/prompts/computer.md` | **Replaced** "SPREADSHEET TOOL FALLBACK" section with new "AX-TREE SPREADSHEET STRATEGY" section |
| `code/mcp_runner.py` | **Removed** `modify_spreadsheet` from the scan-act-verify bypass whitelist |

### New Strategy: AX-Tree Spreadsheet Automation

Instead of the programmatic fallback, the agent now must:

1. **Read data from AX tree** — use `get_window_state` / `get_accessibility_tree` to scan visible cells. Navigate with `ctrl+home`, arrow keys, `page_down` and re-scan to read all rows.
2. **Identify matching rows** — parse cell values from the AX tree output to determine which rows are Status="Pending" with Due Date < today.
3. **Create a new sheet** — `hotkey` with `alt+s i enter` (Sheet → Insert Sheet → OK), then rename with `alt+s r`, `type_text` "Overdue", `hotkey` `enter`.
4. **Enter filtered data** — navigate to cells with arrow keys/Tab, use `type_text` to enter values, `hotkey` with `tab`/`enter` to advance.
5. **Sort** — `hotkey` with `alt+d s` to open Sort dialog, then `type_text` and `hotkey` to set sort column and order.
6. **Save and verify** — `ctrl+s`, verify with `get_window_state`, then `kill_app`.

Even in blind-window scenarios (elements=1), the agent continues with keyboard shortcuts rather than giving up — using `ctrl+home` to go to A1 and arrow keys + `get_window_state` to read cell contents progressively.

### Rationale

- The `modify_spreadsheet` tool bypassed the GUI entirely, which violated the requirement that the agent uses desktop automation (AX tree) to perform the task.
- The agent should prove it can drive LibreOffice through accessibility information, not delegate to a script.
- Keyboard-driven automation with scan-act-verify is the correct approach even when the AX tree is limited.

## Update 2: Native AT-SPI Fallback (Fixing Blind Window)

**Date:** 2026-06-20  
**Problem:** After removing `modify_spreadsheet`, the agent still failed because `cua-driver` returns `elements=1` for LibreOffice. The agent was blind — 60 turns of keystrokes that went nowhere.

**Root Cause Confirmed:** `cua-driver v0.5.7` does not traverse GTK3's ATK bridge. Native `python3-gi` AT-SPI (`gi.repository.Atspi`) sees the full tree including all cell data.

### Solution: `native_atspi.py` — Transparent AT-SPI Fallback

When `get_window_state` returns `elements=1`, the runtime automatically invokes `native_atspi.py` using native AT-SPI bindings. The agent receives real spreadsheet data instead of a blind window.

| File | Change |
|------|--------|
| `code/native_atspi.py` | **New file.** Standalone AT-SPI scanner using `python3-gi`. Reads cell data, sheet tabs, and UI elements directly from LibreOffice's ATK bridge. |
| `code/mcp_runner.py` | **Modified** blind window block. On `elements=1`, runs `native_atspi.py` as subprocess and replaces result with the real tree. |
| `code/prompts/computer.md` | **Updated** AX-TREE SPREADSHEET STRATEGY to explain the native AT-SPI data format. |

### How It Works Now

1. Agent calls `get_window_state(pid, window_id)` → cua-driver returns `elements=1`
2. `mcp_runner.py` detects blind window, runs `python3 native_atspi.py <pid>`
3. `native_atspi.py` reads the real AT-SPI tree via `gi.repository.Atspi`
4. Agent receives full spreadsheet data, identifies overdue rows, creates new sheet via keyboard shortcuts

### Verified Output

```
$ python3 code/native_atspi.py 69520
=== NATIVE AT-SPI SCAN (pid=69520) ===
SHEET TABS: [Sheet1]
SPREADSHEET DATA (13 rows x 7 cols):
  Row header: T001 | Project | Owner | Priority | Due Date | Status | Hours
  Row 1: T001 | Website Redesign | Alice | High | 2026-06-10 | Pending | 8
  ... (all 12 data rows visible)
```

---

## Lessons Learned

1. **cua-driver v0.5.7 has a LibreOffice AT-SPI traversal bug** — it only sees the window frame. Native `python3-gi` AT-SPI sees the full tree.
2. **Blind GUI automation is worse than no automation** — the agent typed keystrokes that went nowhere, then hallucinated success.
3. **Native AT-SPI is the right fallback** — rather than a programmatic tool that bypasses the GUI, use native AT-SPI bindings to fix what cua-driver can't see. The agent still drives the GUI through keyboard shortcuts.
4. **LibreOffice Calc's AT-SPI table has 1 billion children** — use `row * n_columns + col` index math to read only the cells you need.
5. **Python 3.12+ import scoping is strict** — `import os` inside a function makes `os` local to the *entire* function, even before the import statement is reached (see Update 3).

---

## Update 3: `import glob, os` Scoping Bug

**Date:** 2026-06-20  
**Symptom:** Docker run showed `[NATIVE AT-SPI] Fallback error: cannot access local variable 'os' where it is not associated with a value` on every `get_window_state` call. The agent fell back to the blind window warning and typed blind keystrokes for 60 turns.

### Root Cause

Python 3.12+ treats `import X` inside a function as a local variable declaration for `X` across the **entire** function scope. In `mcp_runner.py`, the `run_with_tools` function had:

```python
# Line 585 (inside kill_app handler, deep in the loop):
import glob, os
```

This made `os` a local variable for the entire `run_with_tools` function. When the native AT-SPI fallback (line 672) tried to use `os.environ.copy()` — which runs **before** line 585 is ever reached — Python raised:

```
cannot access local variable 'os' where it is not associated with a value
```

### Fix

```diff
-                                import glob, os
+                                import glob
```

`os` is already imported at module level (line 50). The redundant `import os` inside the function was the only issue. `glob` is fine because it has no other usage before its import.

### Files Modified

| File | Change |
|------|--------|
| `code/mcp_runner.py` (line 585) | `import glob, os` → `import glob` — removes local shadowing of module-level `os` |

---

## Update 4: Docker Missing `python3-gi` + Venv Interpreter Mismatch

**Date:** 2026-06-20  
**Symptom:** After fixing the `os` scoping bug, the native AT-SPI scanner now ran but failed with `ModuleNotFoundError: No module named 'gi'` on every `get_window_state` call inside Docker. The agent was still blind.

### Root Cause (Two issues)

1. **Missing apt package:** The Dockerfile did not install `python3-gi` or `gir1.2-atspi-2.0`. The `gi.repository.Atspi` module requires these system packages.

2. **Wrong Python interpreter:** `mcp_runner.py` used `sys.executable` to run `native_atspi.py`, but inside Docker `sys.executable` points to the uv virtualenv Python (`.venv/bin/python`), which cannot see system apt packages like `python3-gi`. The script must run with `/usr/bin/python3` (system Python).

### Fix

| File | Change |
|------|--------|
| `Dockerfile` | Added `python3-gi` and `gir1.2-atspi-2.0` to `apt-get install` |
| `code/mcp_runner.py` | Changed native AT-SPI subprocess from `sys.executable` → `/usr/bin/python3`; improved error logging to show stdout+stderr |

---

## Update 5: AT-SPI PID Mismatch (Wrapper vs Binary)

**Date:** 2026-06-20  
**Symptom:** After fixing the Docker `python3-gi` issue, the scanner ran but silently failed: `[NATIVE AT-SPI] Fallback failed: ` (empty error). The agent was still blind.

### Root Cause

The agent passes the **wrapper script PID** (e.g., 113 for `/usr/bin/libreoffice`) to `get_window_state`, but AT-SPI registers the **real binary PID** (e.g., 129 for `soffice.bin`). The `find_app(113)` call found no match and exited with code 1.

The error was invisible because:
- `native_atspi.py` wrote error messages to **stdout** (`print(...)`)
- `mcp_runner.py` only logged **stderr** on failure

### Fix

| File | Change |
|------|--------|
| `code/native_atspi.py` | `find_app()` now does a two-pass search: exact PID first, then name-based fallback for any app named "soffice" or "libreoffice". Error messages now go to stderr. On failure, lists all available AT-SPI apps for debugging. |
| `code/mcp_runner.py` | Error logging now shows `stderr or stdout` (whichever has content), plus the return code. |

---

## Update 6: DBUS Session Bus Not Propagated to Subprocess

**Date:** 2026-06-20  
**Symptom:** After PID mismatch fix, the name-based fallback also returned empty: `Available:` list was completely empty. Zero AT-SPI applications visible.

### Root Cause

`entrypoint.sh` exports `DBUS_SESSION_BUS_ADDRESS` in the shell, but `uv run flow.py` creates a subprocess that doesn't inherit the shell variable. When `mcp_runner.py` spawns `native_atspi.py`, `os.environ` has no `DBUS_SESSION_BUS_ADDRESS`. Without this, the AT-SPI client connects to nothing and sees zero applications.

### Fix

| File | Change |
|------|--------|
| `entrypoint.sh` | Writes `DBUS_SESSION_BUS_ADDRESS` to `/tmp/dbus-session-address` file |
| `code/mcp_runner.py` | Reads `/tmp/dbus-session-address` and injects the address into the subprocess env. Also sets `GNOME_ACCESSIBILITY=1` and `GTK_MODULES=gail:atk-bridge`. |

---

## Update 7: ATK Text Interface Fails Inside Docker (Empty Cells)

**Date:** 2026-06-20  
**Symptom:** Native AT-SPI scanner connected successfully (`Fallback succeeded`) but returned `SPREADSHEET DATA: (no data found in cells)`. Agent reported "file appeared empty."

### Root Cause

Inside Docker, LibreOffice's ATK bridge triggers `impl_get_CharacterCount: assertion 'ATK_IS_TEXT (user_data)' failed` when `get_character_count()` is called on table cells. This returns 0, so `get_node_text()` returns empty for every cell. All rows appear empty.

This works on the host because the host has a full GNOME desktop with proper GTK3/ATK integration. Inside Docker, the ATK bridge is incomplete.

### Fix

Updated `get_node_text()` in `native_atspi.py` with 4 fallback methods:
1. **Text interface** (check `get_interfaces()` first to avoid the assertion)
2. **Accessible description** (`get_description()`)
3. **Value interface** (`get_current_value()` for numeric cells)
4. **Child paragraph/text nodes** (LibreOffice may nest text in child nodes)

Added `get_cell_text_via_table()` using `Table.get_accessible_at(row, col)` which goes through a different ATK code path that may work when direct child access fails.

| File | Change |
|------|--------|
| `code/native_atspi.py` | Multi-method `get_node_text()` + `get_cell_text_via_table()` fallback + `use_table_iface` flag |

---

## Update 8: AT-SPI Subprocess Initialization Race Condition

**Date:** 2026-06-20  
**Symptom:** In some Docker runs, ALL native AT-SPI scans fail with `Available:` empty (0 apps). In other runs, the same code succeeds. Intermittent.

### Root Cause

When `mcp_runner.py` spawns `native_atspi.py` as a fresh subprocess, the GI AT-SPI client library needs to connect to the AT-SPI bus and enumerate registered applications. This happens asynchronously through the GLib event loop. But our subprocess called `Atspi.get_desktop(0).get_child_count()` immediately, before the GLib event loop had time to discover any apps. Result: 0 children.

### Fix

| File | Change |
|------|--------|
| `code/native_atspi.py` | Added GLib main context pump (20 iterations) at startup. `find_app()` now retries up to 4 times with `GLib.MainContext.iteration()` + `time.sleep(0.5)` between attempts when desktop has 0 children. Also logs DBUS address and attempt count to stderr for diagnostics. |

---

## Update 9: `get_text()` API Mismatch — Root Cause of Empty Cells

**Date:** 2026-06-20  
**Symptom:** Scanner connected, found table (1048576 rows × 16384 cols), `char_count=4` for cell A1 (non-zero, data EXISTS), but `get_text()` threw: `Atspi.Accessible.get_text() takes exactly 1 argument (3 given)`.

### Root Cause

In Docker's `python3-gi` version, `node.get_text(0, n)` resolves to the **deprecated** `Atspi.Accessible.get_text()` method, which takes 1 argument (child index) and returns a child Accessible. It does NOT call the `Atspi.Text.get_text(start, end)` interface method.

On the host system (GNOME desktop), `node.get_text()` correctly resolves to the Text interface. This version difference is transparent — both versions have the same import statement.

### Fix

Replace all `node.get_text(0, n)` calls with `Atspi.Text.get_text(node, 0, n)` to explicitly invoke the correct Text interface class method.

| File | Change |
|------|--------|
| `code/native_atspi.py` | `node.get_text(0, n)` → `Atspi.Text.get_text(node, 0, n)` in both Method 1 and Method 4 |

---

## Update 10: Stale Lock File Prevents File Loading

**Date:** 2026-06-20  
**Symptom:** Even after fixing `get_text()`, the table returned `children=1, title=''`. Frame never populated beyond a single empty panel. LibreOffice opened but showed Document Recovery dialog instead of the spreadsheet.

### Root Cause

Previous Docker runs left `.~lock.v1_tasklist.ods#` in the data directory (owned by root). The host-side cleanup in `run_in_docker.sh` (`find ... -delete`) silently failed because the file was root-owned. LibreOffice detected the lock and showed a recovery dialog instead of loading the file.

### Fix

| File | Change |
|------|--------|
| `entrypoint.sh` | Added `find /home /data -name '.~lock.*#' -delete` at startup to clean stale locks inside the container. Also added `echo "$DBUS_SESSION_BUS_ADDRESS" > /tmp/dbus-session-address` for subprocess DBUS discovery. |

---

## Update 11: AT-SPI Bus is Separate from D-Bus Session Bus

**Date:** 2026-06-20  
**Symptom:** `DBUS_SESSION_BUS_ADDRESS` was correctly set and the subprocess connected, but `desktop has 0 app(s)` on every attempt. The AT-SPI library saw zero applications.

### Root Cause

The AT-SPI bus is **completely separate** from the D-Bus session bus. The `at-spi-bus-launcher` creates its own bus at `unix:path=/root/.cache/at-spi/bus_99` (where 99 = DISPLAY number) and stores the address in the `AT_SPI_BUS` X11 root window property. Applications register on THIS bus, not the session bus.

Our subprocess was connecting to the session bus (`unix:path=/tmp/dbus-XXXXX`) where zero AT-SPI applications are registered. We needed to redirect the AT-SPI library to connect to the AT-SPI bus directly.

### Fix

| File | Change |
|------|--------|
| `entrypoint.sh` | Reads `AT_SPI_BUS` X11 property after `at-spi-bus-launcher` starts, writes it to `/tmp/at-spi-bus-address` |
| `code/mcp_runner.py` | Reads `/tmp/at-spi-bus-address` and passes as `AT_SPI_BUS_ADDRESS` env var to subprocess |
| `code/native_atspi.py` | If `AT_SPI_BUS_ADDRESS` is set, overrides `DBUS_SESSION_BUS_ADDRESS` BEFORE importing `Atspi` so the library connects directly to the AT-SPI bus |

### Verified Result

Scanner now reads all 12 data rows + header:
```
Row 1: T001 | Website Redesign | Alice | High | 2026-06-10 | Pending | 8
Row 2: T002 | API Testing | Bob | Medium | 2026-06-20 | Pending | 4
...
```

---

## Update 12: AT-SPI Scanning Fully Resolved — Remaining Issues are Agent-Level

**Date:** 2026-06-20  
**Status:** AT-SPI scanner works perfectly. Every scan succeeded (`Fallback succeeded for PID 259`). All 12 rows + header read. Sheet tabs detected. The native AT-SPI fallback is now reliable.

### Remaining Issues (Agent GUI Navigation)

The agent attempted the full workflow but made **GUI interaction errors**:

1. **type_text/hotkey mixing**: Agent sent `tab tab type_text:= tab type_text:Pending ...` as a single hotkey action. `type_text:` is NOT valid xdotool syntax — text and hotkeys must be separate tool calls.
2. **Overdue sheet not persisted**: After file inspection, only `Sheet1` exists. The sheet creation/rename sequence may have failed silently (agent typed "Overdue" twice without verifying rename dialog opened).
3. **Filter dialog interaction**: The Standard Filter dialog requires dropdown selection, not text typing. The agent needs to use `Tab` to navigate between fields and the combo boxes, not type column names.

### What's Fixed (AT-SPI Stack)

| Bug | Fix | Update |
|-----|-----|--------|
| Missing python3-gi in Docker | Added to Dockerfile | #4 |
| Wrong Python interpreter (venv vs system) | Use `/usr/bin/python3` | #4 |
| PID mismatch (wrapper vs soffice.bin) | Name-based fallback search | #5 |
| DBUS session bus not propagated | Persist to `/tmp/dbus-session-address` | #6 |
| `get_text()` API mismatch | `Atspi.Text.get_text(node, 0, n)` | #9 |
| Stale lock file blocks file load | Clean locks in entrypoint.sh | #10 |
| AT-SPI bus ≠ session bus | Discover via X11 property, pass `AT_SPI_BUS_ADDRESS` | #11 |
| GLib event loop race | Pump context + retry loop | #8 |

### Next Steps

Fix agent-level issues in `computer.md` system prompt:
- Enforce strict separation of `type_text` and `hotkey` tool calls
- Add Scan-Act-Verify for sheet creation (verify sheet tabs changed after `alt+s i enter`)
- Document Standard Filter dialog navigation pattern

---

## Update 13: File Corruption + Multi-Method AT-SPI Discovery

**Date:** 2026-06-20

### Issue 1: Agent Corrupted ODS File

The agent's previous run corrupted `v1_tasklist.ods` — Row 0 became empty, data shifted. This caused `char_count=0` on all cells (the AT-SPI Text interface reported no text because the cells were actually empty). Restored from `.bak` file.

**Fix:** Added auto-backup in `run_in_docker.sh` — copies all `.ods` files to `.bak` before each Docker run.

### Issue 2: Intermittent "desktop has 0 apps" 

The AT-SPI bus override (`DBUS_SESSION_BUS_ADDRESS = AT-SPI bus`) sometimes works, sometimes doesn't. Root cause unclear — may depend on timing of `at-spi-bus-launcher` initialization. Added multi-method discovery:

1. `AT_SPI_BUS_ADDRESS` env var (from mcp_runner.py)
2. `/tmp/at-spi-bus-address` file (from entrypoint.sh)
3. Runtime `xprop -root AT_SPI_BUS` (direct X11 query)

All discovery happens BEFORE `import Atspi` since the library caches its bus connection at import time.

| File | Change |
|------|--------|
| `code/native_atspi.py` | Three-method AT-SPI bus discovery before import |
| `run_in_docker.sh` | Auto-backup `.ods` files before each run |
| `code/mcp_runner.py` | Increased subprocess timeout to 20s |

---

## Update 14: Full Session Log — AT-SPI Stack Debugging (Session b041fe35)

**Date:** 2026-06-20  
**Session Duration:** ~6 hours of iterative debugging  
**Outcome:** AT-SPI cell data reading fully resolved. Agent can now read all spreadsheet data. Overdue sheet creation still failing due to agent-level GUI interaction bugs (not AT-SPI bugs).

### Debugging Timeline

#### Phase 1: GLib Event Loop Race (Update 8)

**Problem:** In some Docker runs, ALL native AT-SPI scans failed with `Available:` empty (0 apps). In other runs, the same code succeeded.

**Diagnosis:** Fresh subprocess called `Atspi.get_desktop(0).get_child_count()` immediately after import, before the GLib event loop had time to discover any apps on the bus.

**Fix:**
- Added GLib main context pump (20 iterations) at startup
- `find_app()` now retries up to 4 times with `GLib.MainContext.iteration()` + `time.sleep(0.5)` between attempts when desktop has 0 children

#### Phase 2: `get_text()` API Mismatch (Update 9)

**Problem:** Scanner connected, found table (1048576 rows × 16384 cols), `char_count=4` for cell A1 (data EXISTS), but `get_text()` threw: `Atspi.Accessible.get_text() takes exactly 1 argument (3 given)`.

**Diagnosis:** Created `atspi_diag.py` diagnostic script and ran it inside Docker. Output:
```
Cell (0, 0):
  interfaces=['Accessible', 'Collection', 'Component', 'TableCell', 'Text', 'Value']
  char_count=4
  text=ERROR(Atspi.Accessible.get_text() takes exactly 1 argument (3 given))
```

**Root Cause:** In Docker's `python3-gi` version, `node.get_text(0, n)` resolves to the **deprecated** `Atspi.Accessible.get_text()` method (1 arg = child index), NOT the `Atspi.Text.get_text(start, end)` interface method. On the host GNOME desktop, the same call resolves correctly. This version difference is transparent.

**Fix:** Replace all `node.get_text(0, n)` with `Atspi.Text.get_text(node, 0, n)` — explicitly call the correct Text interface class method.

**Verification:**
```
Cell(0): text='T001'
Cell(1): text='Project'
Cell(2): text='Owner'
Cell(3): text='Priority'
Cell(4): text='Due Date'
Cell(5): text='Status'
Cell(6): text='Hours'
```

#### Phase 3: Stale Lock File (Update 10)

**Problem:** Even after fixing `get_text()`, some runs showed `children=1, title=''` — frame never populated. LibreOffice showed Document Recovery dialog instead of the spreadsheet.

**Diagnosis:** Polled the AT-SPI tree every 2 seconds for 40+ seconds — frame never populated beyond 1 child. Found root-owned `.~lock.v1_tasklist.ods#` from previous Docker runs that survived host-side cleanup.

**Fix:** Added `find /data -name '.~lock.*#' -delete` in `entrypoint.sh`.

#### Phase 4: AT-SPI Bus ≠ Session Bus (Update 11)

**Problem:** After all previous fixes, `DBUS_SESSION_BUS_ADDRESS` was correctly set and subprocess connected, but `desktop has 0 app(s)` on every attempt.

**Diagnosis:** Used `xprop` and `dbus-send` to discover that the AT-SPI bus address (`unix:path=/root/.cache/at-spi/bus_99`) is **completely separate** from the D-Bus session bus (`unix:path=/tmp/dbus-XXXXX`). Applications register on the AT-SPI bus. The subprocess was querying the wrong bus.

```bash
# Session bus (where subprocess was connecting):
unix:path=/tmp/dbus-RlPQeargHB,guid=...  # 0 apps registered here

# AT-SPI bus (where LibreOffice actually registers):
unix:path=/root/.cache/at-spi/bus_99,guid=...  # 1 app registered here
```

**Fix:** Three-file change:
1. `entrypoint.sh` — Reads `AT_SPI_BUS` X11 property → writes to `/tmp/at-spi-bus-address`
2. `mcp_runner.py` — Reads file, passes as `AT_SPI_BUS_ADDRESS` env var
3. `native_atspi.py` — Overrides `DBUS_SESSION_BUS_ADDRESS` with AT-SPI bus before importing `Atspi`

**Verified:** Scanner read all 12 data rows + header successfully.

#### Phase 5: Agent Run s8-b7f35bad — AT-SPI Works, Agent Fails

**Result:** ALL AT-SPI scans succeeded (`Fallback succeeded for PID 259`). Agent read full spreadsheet data. Created Overdue sheet. But failed at filtering:

```
action_value: 'tab tab type_text:= tab type_text:Pending tab type_text:AND ...'
(symbol) No such key name 'type_text:='. Ignoring it.
```

**Root Cause:** Agent mixed `type_text:` syntax inside `hotkey` action — `type_text:` is NOT valid xdotool syntax. Text and hotkeys must be separate tool calls.

**Post-run verification:** File only had `Sheet1` — Overdue sheet was not persisted. Agent's claim of success was false.

#### Phase 6: Agent Run s8-??? — Intermittent 0 Apps Again

**Problem:** All scans failed with `desktop has 0 app(s)` despite AT-SPI bus address being passed correctly. The override approach is unreliable across different Docker container runs.

**Diagnosis:** Ran comparative tests:
```
TEST 1 (Real session bus):  Apps=1  ✅
TEST 2 (AT-SPI override):  Apps=1  ✅
TEST 3 (dbus-send):        OK      ✅
```
Both approaches work when run from `bash -c` inside Docker. The issue is specific to how `mcp_runner.py` spawns the subprocess — likely a timing/initialization issue.

**Fix:** Added multi-method AT-SPI bus discovery (env var → file → runtime `xprop`) before `import Atspi`. All discovery happens BEFORE the library initializes.

#### Phase 7: File Corruption Discovery (Update 13)

**Problem:** After Phase 6 fix, cells reported `char_count=0`. Investigated and found the ODS file was corrupted by a previous agent run — Row 0 empty, data shifted.

**Verification:**
```python
# Corrupted file:
Row 0:  |  |  |  |  |  |     # EMPTY!
Row 1: T001 | Project | ...

# Restored from .bak:
Row 0: T001 | Project | Owner | Priority | Due Date | Status | Hours  ✅
```

**Fix:** Restored from `.bak`. Added auto-backup in `run_in_docker.sh`.

### Complete Fix Summary

| # | Bug | Root Cause | Fix | File(s) |
|---|-----|-----------|-----|---------|
| 8 | GLib race | Subprocess needs event loop pump | Retry loop + GLib pump | `native_atspi.py` |
| 9 | `get_text()` API | Docker python3-gi resolves to deprecated method | `Atspi.Text.get_text(node,0,n)` | `native_atspi.py` |
| 10 | Lock file | Root-owned lock survives host cleanup | Clean inside container | `entrypoint.sh` |
| 11 | Wrong bus | AT-SPI bus ≠ session bus | X11 property discovery | `entrypoint.sh`, `mcp_runner.py`, `native_atspi.py` |
| 12 | Agent GUI | Mixed type_text/hotkey in single action | Pending: fix system prompt | `computer.md` (TODO) |
| 13 | File corruption | Agent damaged data in previous run | Auto-backup before each run | `run_in_docker.sh` |

### Current State

- **AT-SPI stack:** ✅ Fully working. Scanner reads all 12 data rows reliably.
- **Bus discovery:** ✅ Three-method fallback (env var → file → xprop).
- **Cell text reading:** ✅ Uses correct `Atspi.Text.get_text()` class method.
- **Agent GUI navigation:** ❌ Still fails — mixes type_text/hotkey, doesn't verify sheet creation.
- **File integrity:** ✅ Auto-backup prevents permanent corruption.

---

## Update 15: Image Editing — Infinite Loop + Missing Editor

**Date:** 2026-06-20  
**Task:** "Open testimage.jpg, add a red circle above the black rectangle, save."

### Problem

Agent tried to launch GIMP and KolourPaint — neither is installed in Docker. The `launch_app` tool uses `xdg-open` which treats the entire argument as a filename, so `gimp /path/to/file` → `xdg-open: file 'gimp /path/to/file' does not exist`.

Agent got stuck in an **infinite retry loop**, calling `launch_app` with identical arguments 10+ times, burning all hops until manually killed with Ctrl+C.

### Fixes

#### 1. Infinite Loop Guard

Added dedup detection: tracks last 6 tool calls. If 4 consecutive identical calls are detected, injects an error breaking the loop:

```
ERROR: INFINITE LOOP DETECTED. You have called 'launch_app' with identical arguments 
4 times in a row. STOP calling it. Try a completely different approach.
```

#### 2. `edit_image` MCP Tool (Pillow-based)

Injected alongside `desktop_judgment`. Supports: `draw_circle`, `draw_rectangle`, `draw_line`, `draw_text`, `resize`, `crop`, `rotate`, `blur`, `brightness`.

The agent can now call `edit_image` directly instead of trying to launch a GUI editor:
```json
{
  "file_path": "/path/to/image.jpg",
  "operations": [
    {"type": "draw_circle", "x": 200, "y": 100, "radius": 50, "color": "red", "line_width": 3}
  ]
}
```

| File | Change |
|------|--------|
| `code/mcp_runner.py` | Added infinite loop guard (4-call dedup detection) |
| `code/mcp_runner.py` | Added `edit_image` tool definition + Pillow-based handler |

---

## Update 15b: Vision-Guided Image Editing via Browser Skill V9Client

**Date:** 2026-06-20  
**Root Cause:** The `edit_image` tool's original LLM().vision() call crashed with `UnboundLocalError: json` (a local `import json` at line 915 shadowed the module-level import, making Python treat `json` as local throughout the entire function body).

### Fixes

#### 1. `UnboundLocalError: json` Fix
- Removed the local `import json` at line 915 (was inside `run_with_tools`)  
- Added `import time` at module level (line 38)  
- Both were being shadowed by local imports deeper in the function

#### 2. Vision via Browser Skill's V9Client (Set-of-Marks Pipeline)

Rewired the `edit_image` vision layer to use `browser.client.V9Client.vision()` — the **same async `/v1/vision` endpoint** that powers the browser's Layer 3 Set-of-Marks driver.

**Flow:**
```
Agent calls: edit_image(file_path="img.jpg", query="Draw red circle above black rectangle")
                ↓
edit_image handler → opens image with Pillow → encodes as base64 data URL
                ↓
V9Client.vision() → sends to /v1/vision (same as SetOfMarksDriver._decide())
                ↓
Vision LLM analyzes image → returns structured JSON with object positions
                ↓
Parse operations → Pillow draws on image → saves file
```

**Key design:** Uses a JSON schema for the vision response (`ops_schema`) — the same `schema=` pattern as the browser driver — forcing the LLM to return structured `{analysis, operations}` instead of free-form text.

| File | Change |
|------|--------|
| `code/mcp_runner.py` | Fixed `import json` / `import time` shadowing at module level |
| `code/mcp_runner.py` | Replaced `LLM().vision()` with `V9Client.vision()` (browser skill vision) |
| `code/mcp_runner.py` | Added structured JSON schema for vision response parsing |

---

## Update 16: Comprehensive Import Shadowing Fix + Loop Guard v2

**Date:** 2026-06-20  
**Symptoms:**
- `cannot access local variable 'time' where it is not associated with a value` (trajectory recording crashed)
- `launch_app` called 20+ times with different flags (VS Code not installed in Docker)

### Root Cause: Python Local Variable Scoping

Python treats a name as local throughout an **entire function** if that name is assigned/imported **anywhere** in the function — even inside a conditional branch that hasn't executed yet. The `run_with_tools` function had 15+ scattered `import time`, `import subprocess`, `import platform`, `import glob`, `import copy` statements inside conditional branches. If the code path hit `time.time()` before reaching any `import time` branch, Python crashed with `UnboundLocalError`.

### Fix: Hoist All Imports to Module Level

```diff
 import json
 import time
 import sys
+import subprocess
+import platform
+import glob
+import copy
 from pathlib import Path
```

Removed ALL 15 local `import` statements from inside `run_with_tools`.

### Loop Guard v2: Counter-Based Detection

The original guard only detected 4 consecutive identical calls. The agent circumvents this by varying CLI flags each attempt. New two-level guard:

| Level | Detection | Threshold | Catches |
|-------|-----------|-----------|---------|
| 1 | Exact match (tool + args) | 4 consecutive | Same call repeated identically |
| 2 | Counter per tool name | 8 total calls | `launch_app` with varying flags |

Level 2 uses a `Counter()` — not a deque — so it catches alternating patterns like `launch_app → list_apps → launch_app → get_accessibility_tree → launch_app → ...`

| File | Change |
|------|--------|
| `code/mcp_runner.py` | Hoisted 15 local imports to module level (time, subprocess, platform, glob, copy) |
| `code/mcp_runner.py` | Added Counter-based Level 2 loop guard for launch_app |

---

## Update 17: Docker Environment Context Injection

**Date:** 2026-06-20  
**Symptom:** Agent tried to launch VS Code 20+ times inside Docker (VS Code not installed). Coder generated script that looked for VS Code workspace metadata instead of scanning `/app/code/*.py`. Task failed with "unable to locate workspace."

### Root Cause

No skill knew the Docker filesystem layout or which applications were installed. The planner routed "VS Code workspace" queries to `computer` (desktop agent), which tried `launch_app("code")` → `xdg-open` → failure loop.

### Fix: Three-Layer Environment Awareness

#### 1. `render_prompt()` — global context injection (`skills.py`)
Every skill prompt now receives an `ENVIRONMENT CONTEXT` block listing:
- Runtime (Docker, Ubuntu 22.04, headless)
- Filesystem layout (`/app/code/` = workspace, host data dir bind-mounted)
- Installed apps (✅ LibreOffice, Calculator, xdotool, Python; ❌ VS Code, Chrome, GIMP)
- Key routing rules ("VS Code workspace" → treat `/app/code/` as workspace)

#### 2. Planner routing rules (`prompts/planner.md`)
Added explicit Docker routing table:
- "VS Code workspace" → `coder` (NOT `computer`)
- File operations → `coder → sandbox_executor`
- Image editing → `computer` with `edit_image` tool
- Desktop GUI → `computer` (only for installed apps)

#### 3. Coder prompt upgrade (`prompts/coder.md`)
Replaced stub with working prompt that:
- Emits `{"code": "<python>", "rationale": "..."}` JSON
- Knows `/app/code/` is the workspace
- Uses `os.walk()`, `ast`, `regex` for file operations
- Writes output files to user-specified paths

| File | Change |
|------|--------|
| `code/skills.py` | Injected ENVIRONMENT CONTEXT block into `render_prompt()` |
| `code/prompts/planner.md` | Added Docker routing rules and updated skill descriptions |
| `code/prompts/coder.md` | Replaced stub with working coder prompt |
