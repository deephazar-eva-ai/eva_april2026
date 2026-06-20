# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "networkx",
#     "pyvis",
# ]
# ///

import sys
import json
from pathlib import Path
import networkx as nx
from pyvis.network import Network

try:
    from persistence import SessionStore
    HAS_PERSISTENCE = True
except ImportError:
    HAS_PERSISTENCE = False

def visualize(session_id: str):
    if HAS_PERSISTENCE:
        store = SessionStore(session_id)
        graph = store.read_graph()
        if graph is None:
            print(f"No graph found for session {session_id}")
            return
    else:
        graph_path = Path("state/sessions") / session_id / "graph.json"
        if not graph_path.exists():
            print(f"Graph not found at {graph_path}")
            return
        payload = json.loads(graph_path.read_text())
        graph = nx.node_link_graph(payload, edges="edges", directed=True)

    net = Network(height="800px", width="100%", directed=True, notebook=False)
    
    # Customize layout to look like a DAG
    net.set_options("""
    var options = {
      "edges": {
        "color": {"inherit": true},
        "smooth": {"type": "cubicBezier", "forceDirection": "vertical", "roundness": 0.4}
      },
      "layout": {
        "hierarchical": {
          "enabled": true,
          "direction": "UD",
          "sortMethod": "directed",
          "nodeSpacing": 200,
          "levelSeparation": 150
        }
      },
      "physics": {
        "hierarchicalRepulsion": {
          "centralGravity": 0.0,
          "springLength": 100,
          "springConstant": 0.01,
          "nodeDistance": 200,
          "damping": 0.09
        },
        "solver": "hierarchicalRepulsion"
      }
    }
    """)

    for n, d in graph.nodes(data=True):
        skill = d.get('skill', 'unknown')
        status = d.get('status', 'unknown')
        
        # Color mapping
        color = '#D3D3D3' # Default light gray
        if status == 'complete':
            color = '#90EE90' # Light green
        elif status == 'failed':
            color = '#FFB6C1' # Light pink
        elif status == 'running':
            color = '#ADD8E6' # Light blue
            
        label = f"[{n}]\\n{skill}"
        # Make the title (tooltip) pretty
        title = json.dumps(d, indent=2, default=str)
        
        net.add_node(n, label=label, title=title, color=color, shape="box")

    for u, v, d in graph.edges(data=True):
        net.add_edge(u, v, title=str(d))

    sandbox_dir = Path("sandbox")
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    output_file = sandbox_dir / f"dag_{session_id}.html"
    net.write_html(str(output_file))
    print(f"Saved interactive DAG visualization to {output_file}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run visualize_dag.py <session_id>")
        sys.exit(1)
    visualize(sys.argv[1])
