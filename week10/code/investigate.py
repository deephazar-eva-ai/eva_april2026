import json
import glob

session = "s8-858544f5"
nodes_dir = f"state/sessions/{session}/nodes"
for p in sorted(glob.glob(f"{nodes_dir}/*.json")):
    with open(p) as f:
        d = json.load(f)
    if d.get("skill") == "browser" and d.get("status") == "failed":
        res = d.get("result", {})
        err = res.get("error", "")
        out = res.get("output", {})
        url = out.get("url")
        goal = out.get("goal")
        actions = out.get("actions", [])
        print(f"Node {d['node_id']} failed:")
        print(f"  URL: {url}")
        print(f"  Goal: {goal}")
        print(f"  Error: {err}")
        if actions:
            print("  Last 3 Actions:")
            for a in actions[-3:]:
                print(f"    Turn {a.get('turn')}: {a.get('actions')} -> {a.get('outcome')}")
