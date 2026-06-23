# GUI Accessibility Blindness Issue (LibreOffice ODS)

## Bug Description
The desktop agent was experiencing an accessibility blindness issue when attempting to automate LibreOffice Calc (`elements=1` returned from `get_window_state`). The agent was unable to see the individual widgets, cells, or menus inside the application, making GUI interaction impossible.

## Root Cause
While `mcp_runner.py` was correctly setting the `SAL_USE_VCLPLUGIN=gtk3` environment variable in its local `env` dictionary (which is required for LibreOffice to expose its internal widgets to the AT-SPI bus), this modified `env` dictionary was **only** being passed to the `cua-driver` subprocess (`p2`). 

The `mcp_server.py` subprocess (`p1`)—which actually executes the `launch_desktop_app` tool to spawn LibreOffice—was entirely missing the `env=env` argument. As a result, LibreOffice launched with the default shell environment, falling back to the standard VCL plugin and appearing completely "blind" to the agent.

## Fix
In `code/mcp_runner.py`, `env=env` was added to the `StdioServerParameters` for `mcp_server.py` (`p1`) inside the `MultiplexedMCPClient` setup. This ensures that the environment variables are correctly inherited by the MCP server and subsequently passed down to the LibreOffice process it launches.

```python
# Before
if use_sudo_user:
    self.p1 = StdioServerParameters(command="sudo", args=["-E", "-u", use_sudo_user, sys.executable, str(MCP_SERVER)])
else:
    self.p1 = StdioServerParameters(command=sys.executable, args=[str(MCP_SERVER)])

# After
if use_sudo_user:
    self.p1 = StdioServerParameters(command="sudo", args=["-E", "-u", use_sudo_user, sys.executable, str(MCP_SERVER)], env=env)
else:
    self.p1 = StdioServerParameters(command=sys.executable, args=[str(MCP_SERVER)], env=env)
```

By ensuring that `SAL_USE_VCLPLUGIN=gtk3` is propagated to the `mcp_server.py` subprocess, the LibreOffice application now properly exposes its complete accessibility tree to the desktop agent.

## Update: Reverting the Fix to Prevent OOM Crashes

### The Secondary Bug
After implementing the fix above to expose the full accessibility tree, the agent experienced an Out-Of-Memory (OOM) crash and an X11 Fatal IO Error. Because LibreOffice Calc exposes every single spreadsheet cell (millions of nodes) to the AT-SPI bus, the `cua-driver` froze and crashed when trying to scan the full tree. The system attempted to fall back to `native_atspi.py`, but that script failed to connect to LibreOffice due to a bug where it forcefully overrode the valid `DBUS_SESSION_BUS_ADDRESS` with a stale cache file.

### The Final Resolution
To allow the agent to successfully use the AX tree without crashing the system, the architecture was intentionally rolled back to rely on the "Blind Window" fallback mechanism:

1. **Restored the "Blind Window" Trigger (`mcp_runner.py`)**: 
   The `env=env` argument was removed from the MCP server subprocess (`p1`). By intentionally *not* passing `SAL_USE_VCLPLUGIN=gtk3` to LibreOffice, it launches with a blocked GUI (`elements=1`). This prevents `cua-driver` from attempting to map the massive tree and avoids the OOM crash.
   
2. **Fixed the Native AT-SPI D-Bus Issue (`native_atspi.py`)**:
   When `elements=1` is detected, the system automatically falls back to `native_atspi.py` to selectively read just the data (capped at 25 rows x 10 columns). The script was modified so it no longer erroneously overrides a perfectly valid `DBUS_SESSION_BUS_ADDRESS`. It now successfully connects to LibreOffice on the session bus and reads the active cells safely.

3. **Restored Original Prompt Strategy (`computer.md`)**:
   The agent's instructions (Trap 7) were reverted to explicitly instruct it to read the SPREADSHEET DATA from the Native AT-SPI fallback text, compute the required rows in its context window, and then manually actuate keyboard shortcuts (`hotkey`) to create the spreadsheet, completely bypassing the massive GUI tree explosion.
