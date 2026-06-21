# Electron Page Tool Debugging Port Bug

## Summary
The desktop agent successfully routed a VS Code code-extraction task to the `computer` skill and attempted to use the `page` tool to evaluate JavaScript in the Electron DOM. However, the `page` tool attached to the wrong PID (the Antigravity editor) instead of the target application (Cursor), causing the script payload (`fs.writeFileSync`) to fail silently and the agent to return an empty JSON response.

## Root Cause
1. **Manual Launch App Invocation**: The LLM invoked the `launch_app` tool with a raw shell command: 
   ```json
   {"name": "code --remote-debugging-port=9222 /home/acer/..."}
   ```
2. **Bypassed `cua-driver`**: In `mcp_runner.py`, the `launch_app` intercept block detected spaces in the string and used `shlex.split()` to execute it directly via `subprocess.Popen`. 
3. **Lost Debugging Port State**: Because the tool call was handled directly by Python's subprocess and bypassed `mux.call_tool("launch_app", ...)`, the underlying `cua-driver` server never saw the `--remote-debugging-port` flag.
4. **Incorrect PID Targeting**: When the agent subsequently invoked the `page` tool, `cua-driver` had no record of Cursor's debug port. As a result, the LLM defaulted to selecting the first available PID it saw in its context window (`pid: 3787`, which belonged to Antigravity) rather than the newly spawned Cursor instance (`pid: 46954`).

## Fix Implementation
Modified the `launch_app` handler in `mcp_runner.py` to correctly intercept and parse these edge-case shell strings before passing them to the multiplexer:

1. **Executable Substitution**: Explicitly map `code` or `vscode` to `cursor`, ensuring the correct binary is launched on systems where standard VS Code is uninstalled.
2. **Port Extraction**: Parse out `--remote-debugging-port=XXXX` from the string and assign it to `tc_args["electron_debugging_port"]`.
3. **Route through Multiplexer**: Pass the sanitized `tc_args` dictionary to `await mux.call_tool(tc_name, tc_args)` instead of executing it via `subprocess.Popen`. This ensures `cua-driver` launches the application, registers the debug port, and makes it available for the `page` tool in subsequent turns.

## Phase 2: Context Isolation & Node Integration Bug
After fixing the PID selection issue, the agent successfully attached to the correct PID (Cursor) and invoked the `page` tool. However, the agent generated a JavaScript payload that attempted to use `require('fs')` to read the workspace and write the summary.

**Root Cause:**
Modern Electron applications (like VS Code and Cursor) run their renderers with `nodeIntegration: false` and `contextIsolation: true` for security reasons. As a result, the Node.js `fs` module is undefined inside the DOM context. The script threw a `ReferenceError: require is not defined`, and the agent subsequently exited without extracting data.

**Fix Implementation:**
Updated `prompts/computer.md` by adding **Trap 11**. This instruction warns the agent that it cannot use Node integration (`require('fs')`) inside Electron `page` scripts and must instead legitimately drive the GUI:
1. Open the global search panel (via DOM or `ctrl+shift+f`).
2. Search for Python comments using regex mode `(#.*|"""[\s\S]*?""")`.
3. Extract the text directly from the search result DOM elements via the `page` tool.
4. Use `hotkey` `ctrl+n` to create a new file, type the extracted text, and save it via `ctrl+s`.

## Phase 3: Planner Skill Splitting & Routing Bug
During the run, the agent still failed to generate the markdown file because the orchestrator unexpectedly invoked the `coder` skill to parse the extracted text and write the file. 

**Root Cause:**
The `planner` AI broke the task down into two separate nodes. It used the `computer` skill to read the VS Code window, but relied on the `coder` skill to handle the file writing because `prompts/planner.md` specified that the `coder` skill should be used for pure data processing and file I/O tasks. This violated the requirement that the task be completed end-to-end via the `computer` skill and the Electron GUI.

**Fix Implementation:**
Updated `prompts/planner.md` to strictly enforce that the `computer` skill must be used **exclusively** for Electron app tasks. A new rule was added forbidding the planner from chaining into the `coder` skill for file I/O or data processing in these workflows. The `computer` skill is now forced to complete the task end-to-end (extracting the text, opening a new file via `ctrl+n`, typing the text, and saving it via `ctrl+s`).

## Phase 4: Ghost Background Process Blocking CDP Initialization
Even after correcting the planner routing and adding the Trap 11 GUI constraints, the agent still failed to complete the task. The trajectory showed that the `launch_app` tool successfully invoked `cursor`, but the agent encountered an error when calling the `page` tool, forcing it to abruptly exit with an empty JSON response.

**Root Cause:**
Cursor was already running in the background (as a ghost process) without the `--remote-debugging-port=9222` flag enabled. When the agent invoked `launch_app`, the OS sent an IPC request to the existing main process to open a new window. Because the existing main process was not initialized with the CDP flag, the debugging port remained closed. This caused the `page` tool to fail with a "Connection Refused" error, blinding the agent to the DOM.

**Fix Implementation:**
Manually killed all background instances of Cursor using `killall -9 cursor`. This ensures that the next `launch_app` call initializes a brand new main process with the `--remote-debugging-port=9222` argument successfully bound, allowing the `page` tool to connect.

## Phase 5: Blind DOM Hallucination & GTK Save Dialog Focus Stealing
In the subsequent run, the agent successfully navigated the application, ran the global search query, and attempted to save the file. However, it hallucinated the search results and accidentally saved the file as `# Python Comments Summary.yaml` inside the workspace instead of `data/python_comments_summary.md`.

**Root Cause:**
1. **Blind DOM Parsing:** The agent evaluated `document.body.innerText` to read the search results. This returned a massive, unformatted dump of all UI text. Instead of correctly parsing it, the agent hallucinated a fake markdown summary containing `example.py` and `another.py`.
2. **GTK Save Dialog Stealing Focus:** When the agent pressed `ctrl+s` to save the new file, the native GTK save dialog failed to reliably capture keyboard focus. The agent typed the intended path (`data/python_comments_summary.md`) directly into the file's editor body. Cursor then defaulted the file name to the first line of the document, resulting in the `.yaml` artifact.

**Fix Implementation:**
Completely rewrote **Trap 11** in `prompts/computer.md` with explicit, robust alternatives:
1. Provided the exact JavaScript payload required to accurately extract search results without hallucination: `Array.from(document.querySelectorAll('.search-view .monaco-list-row')).map(row => row.innerText).join('\n')`.
2. Forbade the use of `ctrl+n` and `ctrl+s` for saving files. The agent is now instructed to open the integrated VS Code terminal (`ctrl+\``) and use `cat << 'EOF' > ...` to echo the exact string directly into the file, bypassing the fragile GTK save dialog entirely.
