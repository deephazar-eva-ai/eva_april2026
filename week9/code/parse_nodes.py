import json
import glob
import os

nodes_dir = "state/sessions/s8-32106dff/nodes"
for p in sorted(glob.glob(f"{nodes_dir}/*.json")):
    with open(p) as f:
        d = json.load(f)
    print(f"Node {d.get('node_id')} | Skill: {d.get('skill')} | Status: {d.get('status')} | Elapsed: {d.get('result', {}).get('elapsed_s', 0):.1f}s | Error: {d.get('result', {}).get('error')}")
    if d.get('skill') == 'browser':
        print(f"  URL: {d.get('result', {}).get('output', {}).get('url')}")
        print(f"  Goal: {d.get('result', {}).get('output', {}).get('goal')}")
    elif d.get('skill') == 'planner':
        print(f"  Successors: {[s.get('skill') for s in d.get('result', {}).get('successors', [])]}")
