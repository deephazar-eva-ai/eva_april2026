#!/usr/bin/env python3
"""Diagnostic script to test ALL possible AT-SPI methods for reading cell values."""
import sys, os, time

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi, GLib

# Pump GLib event loop
ctx = GLib.MainContext.default()
for _ in range(50):
    ctx.iteration(False)
time.sleep(1)

desktop = Atspi.get_desktop(0)
n = desktop.get_child_count()
print(f"Desktop: {n} apps")

app = None
for i in range(n):
    a = desktop.get_child_at_index(i)
    if a and (a.get_name() or "").lower() in ("soffice", "libreoffice"):
        app = a
        print(f"Found: {a.get_name()} pid={a.get_process_id()}")
        break

if not app:
    print("No soffice app found!")
    for i in range(n):
        a = desktop.get_child_at_index(i)
        if a:
            print(f"  App {i}: {a.get_name()} pid={a.get_process_id()}")
    sys.exit(1)

# Find table
def find_table(node, depth=0):
    if not node or depth > 8:
        return None
    try:
        role = node.get_role_name()
        if role == "table":
            return node
        nc = node.get_child_count()
        for i in range(min(nc, 30)):
            r = find_table(node.get_child_at_index(i), depth+1)
            if r:
                return r
    except:
        pass
    return None

frame = app.get_child_at_index(0)
table = find_table(frame)
if not table:
    print("No table found!")
    sys.exit(1)

ncols = table.get_n_columns()
nrows = table.get_n_rows()
print(f"Table: {nrows} rows x {ncols} cols")
print(f"Table interfaces: {table.get_interfaces()}")

# Test first 7 cells with EVERY possible method
for c in range(7):
    print(f"\n--- Cell (0, {c}) ---")
    
    # Method A: Direct child access
    cell_a = table.get_child_at_index(c)
    if cell_a:
        print(f"  child_at_index({c}):")
        print(f"    name={cell_a.get_name()!r}")
        print(f"    role={cell_a.get_role_name()}")
        print(f"    interfaces={cell_a.get_interfaces()}")
        try:
            print(f"    description={cell_a.get_description()!r}")
        except Exception as e:
            print(f"    description=ERROR({e})")
        try:
            cc = cell_a.get_character_count()
            print(f"    char_count={cc}")
            if cc > 0:
                print(f"    text={cell_a.get_text(0, cc)!r}")
        except Exception as e:
            print(f"    text=ERROR({e})")
        try:
            v = cell_a.get_current_value()
            print(f"    value={v}")
        except Exception as e:
            print(f"    value=ERROR({e})")
        # Check children
        try:
            cnc = cell_a.get_child_count()
            print(f"    child_count={cnc}")
            for ci in range(min(cnc, 5)):
                child = cell_a.get_child_at_index(ci)
                if child:
                    print(f"      child[{ci}] role={child.get_role_name()} name={child.get_name()!r}")
                    try:
                        cn = child.get_character_count()
                        if cn > 0:
                            print(f"        text={child.get_text(0, cn)!r}")
                    except:
                        pass
        except Exception as e:
            print(f"    children=ERROR({e})")
    
    # Method B: Table.get_accessible_at()
    try:
        cell_b = table.get_accessible_at(0, c)
        if cell_b:
            print(f"  get_accessible_at(0, {c}):")
            print(f"    name={cell_b.get_name()!r}")
            try:
                cc = cell_b.get_character_count()
                print(f"    char_count={cc}")
                if cc > 0:
                    print(f"    text={cell_b.get_text(0, cc)!r}")
            except Exception as e:
                print(f"    text=ERROR({e})")
    except Exception as e:
        print(f"  get_accessible_at=ERROR({e})")
    
    # Method C: Table column/row description
    try:
        col_desc = table.get_column_description(c)
        print(f"  column_description({c})={col_desc!r}")
    except Exception as e:
        print(f"  column_description=ERROR({e})")

# Method D: Table row_column_extents_at_index
print("\n--- Table header info ---")
try:
    header = table.get_column_header(0)
    if header:
        print(f"  col_header(0): name={header.get_name()!r}")
except Exception as e:
    print(f"  col_header=ERROR({e})")
