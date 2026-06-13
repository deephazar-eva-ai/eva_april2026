import json

with open("state/sessions/s8-858544f5/nodes/n_002.json") as f:
    d = json.load(f)

res = d.get("result", {})
actions = res.get("output", {}).get("actions", [])
for a in actions:
    print(f"Turn {a.get('turn')}: {a.get('actions')} -> {a.get('outcome')}")
