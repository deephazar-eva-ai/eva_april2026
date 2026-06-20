import sys

with open("mcp_runner.py", "r") as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    # lines 268 to 497 are indices 267 to 496
    if 267 <= i <= 496:
        # Add 4 spaces
        new_lines.append("    " + line)
    else:
        new_lines.append(line)

with open("mcp_runner.py", "w") as f:
    f.writelines(new_lines)
