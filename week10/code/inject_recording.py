import os
from pathlib import Path

with open('code/flow.py', 'r') as f:
    lines = f.readlines()

new_lines = []
in_while_block = False
i = 0

while i < len(lines):
    line = lines[i]
    
    if line.strip() == "while True:":
        # Inject the recording logic before the while True block
        new_lines.append("        from mcp_runner import MultiplexedMCPClient\n")
        new_lines.append("        from pathlib import Path\n")
        new_lines.append("        import os\n")
        new_lines.append("        import shutil\n")
        new_lines.append("        \n")
        new_lines.append("        async with MultiplexedMCPClient() as session_mux:\n")
        new_lines.append("            trajectory_dir = str(Path(__file__).parent / \"trajectories\" / sid)\n")
        new_lines.append("            if \"start_recording\" in session_mux.tool_map:\n")
        new_lines.append("                try:\n")
        new_lines.append("                    rec_res = await session_mux.call_tool(\"start_recording\", {\"output_dir\": trajectory_dir})\n")
        new_lines.append("                    print(f\"DEBUG: start_recording result: {rec_res}\")\n")
        new_lines.append("                    replay_dir = Path(__file__).parent / \"replay\"\n")
        new_lines.append("                    os.makedirs(replay_dir, exist_ok=True)\n")
        new_lines.append("                    source_html = Path(__file__).parent / \"trajectory_player.html\"\n")
        new_lines.append("                    if source_html.exists():\n")
        new_lines.append("                        shutil.copy2(source_html, replay_dir / f\"trajectory_replay_{sid}.html\")\n")
        new_lines.append("                except Exception as e:\n")
        new_lines.append("                    print(f\"DEBUG: Failed to start recording: {e}\")\n")
        new_lines.append("\n")
        new_lines.append("            try:\n")
        
        in_while_block = True
    
    if in_while_block:
        if line.strip() == "return formatter_answer or \"\"":
            # Indent the line
            new_lines.append("                " + line)
            # Add the finally block
            new_lines.append("            finally:\n")
            new_lines.append("                if \"stop_recording\" in session_mux.tool_map:\n")
            new_lines.append("                    try:\n")
            new_lines.append("                        await session_mux.call_tool(\"stop_recording\", {})\n")
            new_lines.append("                        print(\"DEBUG: stop_recording called.\")\n")
            new_lines.append("                    except Exception:\n")
            new_lines.append("                        pass\n")
            i += 1
            continue
            
        if line.strip() == "" and i > 0 and lines[i-1].strip() == "return formatter_answer or \"\"":
             in_while_block = False # past the block

        if line.strip() != "" and line.startswith("        "):
            new_lines.append("        " + line)
        else:
            if line.strip() == "":
                new_lines.append(line)
            else:
                new_lines.append(line)
    else:
        new_lines.append(line)
        
    i += 1

with open('code/flow.py', 'w') as f:
    f.writelines(new_lines)
