import json
import glob
import os

nodes_dir = "state/sessions/s8-b761105e/nodes"
nodes = []
for p in sorted(glob.glob(f"{nodes_dir}/*.json")):
    with open(p) as f:
        nodes.append(json.load(f))

total_time = 0
total_cost = 0
for d in nodes:
    res = d.get('result', {})
    total_time += res.get('elapsed_s', 0)
    total_cost += res.get('cost', 0)

b_nodes = [n for n in nodes if n.get('skill') == 'browser']
for b in b_nodes:
    print(f"{b['node_id']} (Status: {b['status']}): Path: {b.get('result', {}).get('output', {}).get('path')} | Goal: {b.get('result', {}).get('output', {}).get('goal')}")

print(f"Total time: {total_time:.2f}s, Total cost: {total_cost:.4f}")

distillers = [n for n in nodes if n.get('skill') == 'distiller']
for d in distillers:
    if d.get('status') == 'complete':
        print(f"Distiller {d['node_id']}: {d.get('result', {}).get('output', {}).get('fields')}")

