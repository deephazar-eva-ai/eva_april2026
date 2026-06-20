I have identified and fixed the two underlying issues that caused the agent to fail the LibreOffice spreadsheet task and get stuck in the `desktop_judgment` loop.

### 1. Fixed the `tool_calls` Mutation Bug (Infinite Loop)
In the trace, the agent kept repeating `desktop_judgment` calls with invalid arguments like `{"key": "f"}` instead of the required schema (`verdict`, `action_type`, `action_value`). 

This happened because `mcp_runner.py` was mutating the `tool_calls` dictionary *in-place* to route arguments to internal system actions (like mapping `desktop_judgment` to `type_text` or `hotkey`). Because Python lists are passed by reference, `messages.append` was capturing the *mutated* version of the LLM's output. In subsequent turns, the LLM saw its own previous history populated with `{"key": "alt+d"}` and incorrectly assumed that was the valid way to invoke the tool. 

**Fix:** Added a `copy.deepcopy(tool_calls)` when recording the agent's turn to the message history. This ensures the LLM's conversation history maintains the exact original JSON it emitted.

### 2. Fixed `xdotool` Sequence Execution for Transient Menus
The agent correctly understood it needed to use space-separated hotkeys (`alt+d f f`) to navigate the LibreOffice `Data -> AutoFilter` menu without losing transient focus between calls.

However, the Python script was concatenating all of these into a single `xdotool` invocation (`xdotool key alt+d f f`). While `xdotool` natively supports a `--delay 50`, that 50ms delay between the shortcut triggers was much too fast for GTK3/VCL to actually render and map the dropdown menu.

**Fix:** Updated the `hotkey` loop in `mcp_runner.py` to invoke `xdotool key` independently for each space-separated segment in the command and explicitly wait `0.3s` (`time.sleep(0.3)`) after each. This provides the host application the necessary time to reliably open dropdown menus before the subsequent keystrokes are injected.

Both fixes have been applied successfully to `mcp_runner.py`. The agent should now correctly execute the `alt+d f f` workflow without failing or exceeding context limits.
