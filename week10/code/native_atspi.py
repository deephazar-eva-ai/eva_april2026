#!/usr/bin/env python3
"""Native AT-SPI scanner for LibreOffice Calc.

When cua-driver returns elements=1 (blind window), this script uses
python3-gi's native Atspi bindings to read the real accessibility tree.

Usage: python3 native_atspi.py <pid>
Output: Formatted text showing spreadsheet data, sheet tabs, and UI state.
"""

import sys
import os
import signal

# Timeout guard — AT-SPI can hang indefinitely on broken sessions
def _timeout_handler(signum, frame):
    print("[NATIVE AT-SPI] ERROR: Scan timed out after 15 seconds", file=sys.stderr)
    sys.exit(1)

signal.signal(signal.SIGALRM, _timeout_handler)
signal.alarm(15)

import gi
gi.require_version('Atspi', '2.0')
import subprocess as _sp

# The AT-SPI bus is SEPARATE from the D-Bus session bus.
# The Atspi library reads DBUS_SESSION_BUS_ADDRESS at import time and caches it.
# We MUST set it to the AT-SPI bus address BEFORE importing Atspi.
# Discovery order: env var → file → xprop (runtime X11 query)
dbus_session = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "(not set)")
display = os.environ.get("DISPLAY", ":99")
os.environ["DISPLAY"] = display  # Ensure DISPLAY is set

atspi_addr = os.environ.get("AT_SPI_BUS_ADDRESS")

if not atspi_addr:
    try:
        with open("/tmp/at-spi-bus-address") as f:
            atspi_addr = f.read().strip()
    except FileNotFoundError:
        pass

if not atspi_addr:
    try:
        r = _sp.run(["xprop", "-root", "-notype", "AT_SPI_BUS"],
                   capture_output=True, text=True, timeout=3,
                   env={"DISPLAY": display})
        if "=" in r.stdout:
            atspi_addr = r.stdout.split('"')[1]
    except Exception:
        pass

if atspi_addr:
    # python3-gi's Atspi bindings discover the accessibility registry through
    # DBUS_SESSION_BUS_ADDRESS. In the Docker desktop run, the normal D-Bus
    # session and the AT-SPI bus are different addresses; using the normal
    # session bus leaves the desktop empty even while LibreOffice is open.
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = atspi_addr
    print(f"[NATIVE AT-SPI] Using AT-SPI bus: {atspi_addr} (was: {dbus_session})", file=sys.stderr)
elif dbus_session != "(not set)":
    print(f"[NATIVE AT-SPI] Using existing session bus: {dbus_session}", file=sys.stderr)
else:
    print(f"[NATIVE AT-SPI] WARNING: No AT-SPI bus found, using session bus: {dbus_session}", file=sys.stderr)

from gi.repository import Atspi, GLib
import time as _time

def _pump_glib(n=50):
    ctx = GLib.MainContext.default()
    for _ in range(n):
        ctx.iteration(False)

# Initial pump to let library settle
_pump_glib(50)


def find_app(target_pid: int):
    """Find the AT-SPI application matching the given PID.
    
    Falls back to name-based search (soffice/libreoffice) if exact PID
    match fails, because the agent often passes the wrapper script PID
    while AT-SPI registers the real soffice.bin PID.
    
    Retries with GLib event loop pump if desktop has 0 children, since
    a fresh subprocess may need time to discover AT-SPI apps.
    """
    import time
    
    for attempt in range(20):
        desktop = Atspi.get_desktop(0)
        n_apps = desktop.get_child_count()
        print(f"[NATIVE AT-SPI] Attempt {attempt+1}: desktop has {n_apps} app(s)", file=sys.stderr)
        
        if n_apps == 0:
            # Pump event loop and retry
            context = GLib.MainContext.default()
            for _ in range(50):
                context.iteration(False)
            time.sleep(0.5)
            continue
        
        # First pass: exact PID match
        for i in range(n_apps):
            app = desktop.get_child_at_index(i)
            if app is None:
                continue
            try:
                if app.get_process_id() == target_pid:
                    return app
            except Exception:
                continue
        
        # Second pass: name-based fallback for LibreOffice
        # The agent passes the wrapper PID but AT-SPI sees soffice.bin's PID
        for i in range(n_apps):
            app = desktop.get_child_at_index(i)
            if app is None:
                continue
            try:
                app_name = (app.get_name() or "").lower()
                if app_name in ("soffice", "libreoffice"):
                    print(f"[NATIVE AT-SPI] PID {target_pid} not found, using '{app.get_name()}' (PID {app.get_process_id()}) instead", file=sys.stderr)
                    return app
            except Exception:
                continue
        
        # Apps exist but none match — no point retrying
        break
    
    return None


def get_node_text(node) -> str:
    """Extract text content from an AT-SPI node.
    
    Tries multiple methods because LibreOffice's ATK bridge inside Docker
    may fail the Text interface ('ATK_IS_TEXT assertion failed').
    """
    # Method 1: Standard Text interface
    try:
        ifaces = node.get_interfaces()
        if "Text" in ifaces:
            n = node.get_character_count()
            if 0 < n <= 1000:
                # Must use Atspi.Text.get_text() class method, not node.get_text()
                # because node.get_text() resolves to deprecated Atspi.Accessible.get_text
                # which takes 1 arg (index) not 2 (start, end)
                return Atspi.Text.get_text(node, 0, n)
    except Exception:
        pass
    
    # Method 2: Accessible description (LibreOffice sometimes puts values here)
    try:
        desc = node.get_description()
        if desc:
            return desc
    except Exception:
        pass
    
    # Method 3: Value interface (for numeric cells)
    try:
        ifaces = node.get_interfaces()
        if "Value" in ifaces:
            val = node.get_current_value()
            if val is not None and val != 0:
                # Check if it's actually a meaningful value
                return str(val)
    except Exception:
        pass
    
    # Method 4: Read text from child paragraph/text nodes
    try:
        nc = node.get_child_count()
        for i in range(min(nc, 3)):
            child = node.get_child_at_index(i)
            if child:
                role = child.get_role_name()
                if role in ("paragraph", "text", "label"):
                    try:
                        cn = child.get_character_count()
                        if 0 < cn <= 1000:
                            return Atspi.Text.get_text(child, 0, cn)
                    except Exception:
                        pass
                    # Try child's name
                    cname = child.get_name()
                    if cname:
                        return cname
    except Exception:
        pass
    
    return ""


def get_cell_text_via_table(table_node, row: int, col: int) -> str:
    """Read a cell value using the Table interface's get_accessible_at().
    
    This may work when direct child access fails because it goes through
    a different ATK code path.
    """
    try:
        cell = table_node.get_accessible_at(row, col)
        if cell:
            return get_node_text(cell)
    except Exception:
        pass
    return ""


def find_node_by_role(root, target_role: str, max_depth: int = 8):
    """DFS search for a node with a specific role name."""
    def _search(node, depth):
        if node is None or depth > max_depth:
            return None
        try:
            role = node.get_role_name()
            if role == target_role:
                return node
            nc = node.get_child_count()
            # Don't iterate into tables (billions of children)
            if role == "table":
                return None
            for i in range(min(nc, 30)):
                result = _search(node.get_child_at_index(i), depth + 1)
                if result:
                    return result
        except Exception:
            pass
        return None
    return _search(root, 0)


def read_spreadsheet_data(table_node, max_rows=25, max_data_cols=10):
    """Read cell data from a LibreOffice Calc table using direct index access.
    
    LibreOffice Calc's AT-SPI table has n_columns cells per row, laid out
    row-major. So cell at (row, col) = child_at_index(row * n_columns + col).
    
    Falls back to Table.get_accessible_at() if direct child access fails.
    """
    try:
        n_cols_total = table_node.get_n_columns()  # 1024 for Calc
    except Exception:
        n_cols_total = 1024
    
    # First, determine how many columns have data by reading row 0
    # Try both direct child access and Table interface
    data_cols = 0
    use_table_iface = False
    
    for c in range(min(max_data_cols + 5, n_cols_total)):
        try:
            cell = table_node.get_child_at_index(c)  # Row 0
            text = get_node_text(cell)
            if not text:
                # Try Table interface as fallback
                text = get_cell_text_via_table(table_node, 0, c)
                if text:
                    use_table_iface = True
            if text:
                data_cols = c + 1
            elif c > data_cols + 2:
                break  # Two consecutive empty cols after last data col
        except Exception:
            break
    
    if data_cols == 0:
        return []
    
    data_cols = min(data_cols, max_data_cols)
    
    # Read rows
    rows = []
    consecutive_empty = 0
    for r in range(max_rows):
        row_data = []
        row_empty = True
        for c in range(data_cols):
            text = ""
            if use_table_iface:
                # Use Table interface (get_accessible_at) which may work
                # when direct child access has broken Text interface
                text = get_cell_text_via_table(table_node, r, c)
            else:
                idx = r * n_cols_total + c
                try:
                    cell = table_node.get_child_at_index(idx)
                    text = get_node_text(cell)
                except Exception:
                    pass
                if not text:
                    text = get_cell_text_via_table(table_node, r, c)
            row_data.append(text)
            if text:
                row_empty = False
        
        if row_empty and r > 0:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                break
        else:
            consecutive_empty = 0
            rows.append(row_data)
    
    return rows


def find_sheet_tabs(root):
    """Find sheet tab names from the document spreadsheet's table name."""
    tabs = []
    
    def _find_doc(node, depth=0):
        if node is None or depth > 8:
            return
        try:
            role = node.get_role_name()
            if role == "document spreadsheet":
                # Each child table's name is "Sheet <SheetName>"
                nc = node.get_child_count()
                for i in range(min(nc, 20)):
                    try:
                        child = node.get_child_at_index(i)
                        if child and child.get_role_name() == "table":
                            tname = child.get_name() or ""
                            # Strip "Sheet " prefix if present
                            if tname.startswith("Sheet "):
                                tname = tname[6:]
                            tabs.append(tname)
                    except Exception:
                        continue
                return
            if role == "table":
                return  # Don't recurse into tables
            nc = node.get_child_count()
            for i in range(min(nc, 30)):
                _find_doc(node.get_child_at_index(i), depth + 1)
                if tabs:  # Found it, stop searching
                    return
        except Exception:
            pass
    
    _find_doc(root)
    return tabs


def walk_ui_elements(node, output, depth=0, max_depth=4, idx_counter=None):
    """Walk non-table UI elements (menus, dialogs, toolbars, tabs)."""
    if idx_counter is None:
        idx_counter = [0]
    if node is None or depth > max_depth or idx_counter[0] > 150:
        return
    
    try:
        role = node.get_role_name()
        name = node.get_name() or ""
    except Exception:
        return
    
    # Skip deep structural noise
    if depth > 2 and role in ("filler", "separator", "redundant object",
                               "section") and not name:
        return
    
    # Skip table and document spreadsheet — handled separately
    if role in ("table", "document spreadsheet"):
        idx_counter[0] += 1
        return
    
    idx = idx_counter[0]
    idx_counter[0] += 1
    
    indent = "  " * depth
    line = f"{indent}[{idx}] {role}"
    if name:
        line += f' "{name}"'
    
    # Add text value for interactive elements
    if role in ("text", "label", "entry", "push button", "toggle button",
                "check box", "combo box", "menu item", "page tab"):
        text = get_node_text(node)
        if text and text != name:
            line += f' value="{text}"'
    
    output.append(line)
    
    # Recurse into children (skip tables)
    try:
        nc = node.get_child_count()
    except Exception:
        return
    
    for i in range(min(nc, 50)):
        try:
            child = node.get_child_at_index(i)
            walk_ui_elements(child, output, depth + 1, max_depth, idx_counter)
        except Exception:
            continue


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 native_atspi.py <pid>")
        sys.exit(1)
    
    target_pid = int(sys.argv[1])
    
    app = find_app(target_pid)
    if not app:
        # List available apps for debugging
        desktop = Atspi.get_desktop(0)
        available = []
        for i in range(desktop.get_child_count()):
            a = desktop.get_child_at_index(i)
            if a:
                try:
                    available.append(f"{a.get_name()}(pid={a.get_process_id()})")
                except Exception:
                    pass
        print(f"[NATIVE AT-SPI] No application found for PID {target_pid}. Available: {', '.join(available[:10])}", file=sys.stderr)
        sys.exit(1)
    
    app_name = app.get_name() or "unknown"
    
    # Find the main frame window
    frame = None
    frame_title = ""
    for i in range(app.get_child_count()):
        child = app.get_child_at_index(i)
        if child and child.get_role_name() == "frame":
            frame = child
            frame_title = child.get_name() or ""
            break
    
    if not frame:
        print(f"[NATIVE AT-SPI] App '{app_name}' (PID {target_pid}) has no frame window")
        sys.exit(1)
    
    parts = []
    parts.append(f"=== NATIVE AT-SPI SCAN (pid={target_pid}) ===")
    parts.append(f"app={app_name} window=\"{frame_title}\"")
    parts.append("")
    
    # 1. Sheet tabs
    tabs = find_sheet_tabs(frame)
    if tabs:
        parts.append(f"SHEET TABS: [{', '.join(tabs)}]")
        parts.append("")
    
    # 2. Find the table and read spreadsheet data
    table_node = find_node_by_role(frame, "table", max_depth=8)
    if table_node:
        table_name = table_node.get_name() or ""
        if table_name.startswith("Sheet "):
            table_name = table_name[6:]
        parts.append(f"ACTIVE TABLE: \"{table_name}\"")
        
        rows = read_spreadsheet_data(table_node, max_rows=25, max_data_cols=10)
        if rows:
            parts.append(f"SPREADSHEET DATA ({len(rows)} rows x {len(rows[0]) if rows else 0} cols):")
            for i, row in enumerate(rows):
                label = "header" if i == 0 else str(i)
                parts.append(f"  Row {label}: {' | '.join(str(v) for v in row)}")
            parts.append("")
        else:
            parts.append("SPREADSHEET DATA: (no data found in cells)")
            parts.append("")
    else:
        parts.append("SPREADSHEET DATA: (table node not found — a dialog may be blocking)")
        parts.append("")
    
    # 3. UI elements (menus, dialogs, toolbars — NOT table cells)
    ui_output = []
    walk_ui_elements(frame, ui_output, depth=0, max_depth=3, idx_counter=[0])
    if ui_output:
        parts.append(f"UI ELEMENTS ({len(ui_output)} nodes):")
        parts.extend(ui_output)
        parts.append("")
    
    # Footer
    parts.append("[NOTE: Element indices are from native AT-SPI, NOT cua-driver.")
    parts.append("Do NOT use them with click actions. Use keyboard shortcuts (hotkey) for ALL interactions.]")
    
    print("\n".join(parts))


if __name__ == "__main__":
    main()
