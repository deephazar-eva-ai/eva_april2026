import json
import glob
from pathlib import Path

session_dir = Path("/home/acer/Documents/DEEPAK/eva_april2026/mainbranch/eva_april2026/week9/code/state/sessions/s8-1130ce81")

nodes = {}
for f in session_dir.glob("nodes/n_*.json"):
    data = json.loads(f.read_text())
    nodes[data["node_id"]] = data

print("== DAG ==")
for nid in sorted(nodes.keys(), key=lambda x: int(x.split(":")[1])):
    n = nodes[nid]
    print(f"{nid} ({n['skill']})")
    if n['skill'] == 'planner':
        print(f"  Plan: {json.dumps(n['result']['output'])}")
    if n['skill'] == 'browser':
        print(f"  Browser Path: {n['result']['output'].get('path')}")
        print(f"  URL: {n['result']['output'].get('url')}")
        print(f"  Final URL: {n['result']['output'].get('final_url')}")
        print(f"  Turns: {n['result']['output'].get('turns')}")
        print(f"  Actions: {json.dumps(n['result']['output'].get('actions'))}")
    if n['skill'] == 'distiller':
        print(f"  Extracted Data: {json.dumps(n['result']['output'])}")
    if n['skill'] == 'critic':
        print(f"  Critic Verdict: {n['result']['output']}")
    print(f"  Cost: {n['result'].get('cost', 0.0)}, Elapsed: {n['result']['elapsed_s']}s")

print("== BROWSER ARTIFACTS ==")
for f in session_dir.glob("browser/*"):
    print(f.name)
