import sys
import asyncio
from mcp_runner import MultiplexedMCPClient

async def replay_trajectory(session_id: str):
    import os
    from pathlib import Path
    trajectory_dir = str(Path(__file__).parent / "trajectories" / session_id)
    print(f"Replaying trajectory from {trajectory_dir}...")
    
    async with MultiplexedMCPClient() as mux:
        if "replay_trajectory" not in mux.tool_map:
            print("Error: replay_trajectory tool is not available in the MCP server.")
            return 1
            
        try:
            result = await mux.call_tool("replay_trajectory", {"trajectory_dir": trajectory_dir})
            print("Replay result:")
            print(result)
            return 0
        except Exception as e:
            print(f"Error replaying trajectory: {e}")
            return 1

def main():
    if len(sys.argv) != 2:
        print("Usage: uv run python replay_trajectory.py <session_id>")
        return 1
        
    session_id = sys.argv[1]
    return asyncio.run(replay_trajectory(session_id))

if __name__ == "__main__":
    sys.exit(main())
