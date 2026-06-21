"""Tool-use loop wrapper around the gateway + MCP server.

When a Session 8 skill declares `tools_allowed: [...]` in agent_config.yaml,
its dispatch goes through `run_with_tools` (below) rather than a single
chat call. The wrapper drives the conversation until the model stops
asking for tool_calls and emits text:

    1. chat(messages, tools=schemas)
    2. if reply.tool_calls is non-empty:
         for each tc: dispatch via MCP, append a `role="tool"` message
         append assistant message with tool_calls
         go to 1
       else:
         return reply.text

The MCP server is the same `mcp_server.py` carried over from S7. We open
one stdio session per skill invocation (the spawn cost is ~100ms and the
session lives only for the lifetime of one node — keeping it short means
no shared mutable state between skills).

This file is small on purpose. If the cost of a per-skill subprocess
becomes the bottleneck, the right fix is a shared session at the
Executor level, not a more clever client here.
"""

from __future__ import annotations

import re
import traceback

class PermissionsError(Exception):
    pass
class StaleStateError(Exception):
    pass
class VisionEscalationError(Exception):
    pass
import json
import time
import sys
import subprocess
import platform
import glob
import copy
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from gateway import LLM

MCP_SERVER = Path(__file__).parent / "mcp_server.py"
MAX_TOOL_HOPS = 200  # Scan-Act-Verify triples tool call count for complex filter dialogs: every field needs scan + act + verify


import os
from contextlib import AsyncExitStack

async def condense_perception(raw_tree: str, query_passed: bool) -> str:
    """Layer 2: Perception Interpretation.
    Filters the AX tree markdown into something an LLM can act on.
    Pre-filter with query arg (native to driver), regex-extract structured rows,
    and summarise with cheap model if still overflowing.
    """
    if "elements=0" in raw_tree:
        return raw_tree
        
    lines = raw_tree.splitlines()
    if len(lines) < 50 and not query_passed:
        return raw_tree  # Small enough, leave intact
        
    import re
    actionable = []
    dropped = 0
    for line in lines:
        # Keep indexed interactive nodes, window headers, and basic structural landmarks
        if re.search(r'\[\d+\]', line) or line.startswith("window_id=") or line.startswith("pid="):
            actionable.append(line)
        elif any(role in line for role in ["window", "dialog", "menu", "toolbar", "tabList"]):
            actionable.append(line)
        else:
            dropped += 1
            
    condensed_text = "\n".join(actionable)
    if dropped > 0:
        condensed_text += f"\n\n[Perception Filter: Dropped {dropped} static/structural rows. Used regex-extraction.]"
        
    # Cost Knob: Summarise with cheap model if still massively overflowing
    if len(condensed_text) > 15000:
        from gateway import LLM
        cheap_model = LLM("groq")
        try:
            summary = await cheap_model.generate(
                system="You are a Perception Interpreter. Condense this huge desktop accessibility tree into just the major interactive landmarks, active menus, and primary content areas. You MUST retain the exact [index] numbers for any interactive elements you preserve. Drop invisible or disabled items.",
                user=condensed_text[:30000] # Safe context bound for groq
            )
            return summary.text + "\n\n[Perception Filter: Summarised via cheap model (groq).]"
        except Exception as e:
            if len(condensed_text) > 8000:
                return condensed_text[:8000] + f"\n\n[Perception Filter: Summariser failed ({e}). TRUNCATED massive tree.]"
            return condensed_text
            
    return condensed_text

class MultiplexedMCPClient:
    def __init__(self):

        import getpass
        import os
        import sys

        use_sudo_user = None

        # Enforce Inner Ring Strategy on Linux
        if platform.system() == "Linux":
            current_user = getpass.getuser()
            is_docker = os.path.exists("/.dockerenv")
            if not is_docker and current_user != "agent_test_user" and not os.environ.get("BYPASS_INNER_RING"):
                print(f"\n[WARNING] BLAST RADIUS ENFORCEMENT: You are running as '{current_user}'.", file=sys.stderr)
                print(f"[WARNING] Switching to 'agent_test_user' to protect your real account...\n", file=sys.stderr)
                use_sudo_user = "agent_test_user"

        env = os.environ.copy()
        if "DISPLAY" not in env:
            env["DISPLAY"] = ":99"
        
        # Guard against Trap 3: Linux Qt Apps
        # Force the Qt Accessibility bridge on globally for any app cua-driver launches
        env["QT_ACCESSIBILITY"] = "1"
        
        # Disable LibreOffice file locking to prevent "Document in Use" errors
        # if a previous agent run crashed and left a .~lock file
        env["SAL_ENABLE_FILE_LOCKING"] = "0"
        
        # Force LibreOffice to use GTK3 VCL plugin for AT-SPI accessibility
        # Without this, only the top-level window frame is visible (elements=1)
        env["SAL_USE_VCLPLUGIN"] = "gtk3"

        if use_sudo_user:
            self.p1 = StdioServerParameters(command="sudo", args=["-E", "-u", use_sudo_user, sys.executable, str(MCP_SERVER)])
        else:
            self.p1 = StdioServerParameters(command=sys.executable, args=[str(MCP_SERVER)])
        
        traj_dir = "/app/trajectories"
        if os.path.exists(traj_dir):
            cmd_sh = f"cd {traj_dir} && exec cua-driver mcp --no-overlay"
        else:
            cmd_sh = "exec cua-driver mcp --no-overlay"

        if use_sudo_user:
            self.p2 = StdioServerParameters(command="sudo", args=["-E", "-u", use_sudo_user, "sh", "-c", cmd_sh], env=env)
        else:
            self.p2 = StdioServerParameters(command="sh", args=["-c", cmd_sh], env=env)
        
    async def __aenter__(self):
        self.stack = AsyncExitStack()
        
        r1, w1 = await self.stack.enter_async_context(stdio_client(self.p1))
        self.mcp1 = await self.stack.enter_async_context(ClientSession(r1, w1))
        await self.mcp1.initialize()
        
        r2, w2 = await self.stack.enter_async_context(stdio_client(self.p2))
        self.mcp2 = await self.stack.enter_async_context(ClientSession(r2, w2))
        await self.mcp2.initialize()
        
        t1 = await self.mcp1.list_tools()
        t2 = await self.mcp2.list_tools()
        
        self.tool_map = {}
        self.tool_schemas = {}
        
        for t in t1.tools:
            self.tool_map[t.name] = self.mcp1
            self.tool_schemas[t.name] = {
                "name": t.name,
                "description": t.description,
                "input_schema": getattr(t, "inputSchema", {})
            }
            
        for t in t2.tools:
            self.tool_map[t.name] = self.mcp2
            self.tool_schemas[t.name] = {
                "name": t.name,
                "description": t.description,
                "input_schema": getattr(t, "inputSchema", {})
            }
            
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stack.aclose()
        import asyncio
        await asyncio.sleep(0.1)

    def get_payload(self, allowed: list[str]) -> list[dict]:
        return [self.tool_schemas[n] for n in allowed if n in self.tool_schemas]

    async def call_tool(self, name: str, args: dict) -> str:
        if name not in self.tool_map:
            return json.dumps({"error": f"Tool {name} not found in any MCP server"})
        session = self.tool_map[name]
        try:
            result = await session.call_tool(name, arguments=args)
            parts = []
            for c in (getattr(result, "content", None) or []):
                ctype = getattr(c, "type", "")
                if ctype == "image":
                    # Cache the latest image for Layer 5 Vision Fallback
                    self.last_image_data = getattr(c, "data", None)
                    if self.last_image_data and not self.last_image_data.startswith("data:"):
                        mime = getattr(c, "mimeType", "image/png")
                        self.last_image_data = f"data:{mime};base64,{self.last_image_data}"
                else:
                    t = getattr(c, "text", None)
                    parts.append(t if t is not None else str(c))
            return "\n".join(parts) if parts else ""
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"})


async def run_with_tools(*, prompt: str, tools_allowed: list[str],
                         agent: str, session_id: str,
                         provider_pin: str | None = None,
                         max_tokens: int = 2048,
                         temperature: float = 0.3) -> dict:
    """Multi-turn chat: dispatch tool_calls via MCP, keep going until the
    model returns text. Returns the FINAL gateway reply dict (so callers
    can read `text`, `provider`, etc. the same way they would for a
    one-shot call)."""
    messages: list[dict] = [{"role": "user", "content": prompt}]
    last_reply: dict = {}

    async with MultiplexedMCPClient() as mux:
        tools_payload = mux.get_payload(tools_allowed)
        
        # Inject the Layer 2b structured action judgment tool if we're a desktop agent
        if "click" in tools_allowed or agent == "computer":
            tools_payload.append({
                "name": "desktop_judgment",
                "description": "Layer 2b Judgment. Decide whether to act on an element or escalate. If you know what to interact with, use 'act'. If there are no viable elements (e.g. game canvas), use 'escalate'.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "verdict": {"type": "string", "enum": ["act", "escalate"]},
                        "element_index": {"type": "integer"},
                        "action_type": {"type": "string", "enum": ["click", "type_text", "press_key", "hotkey"]},
                        "action_value": {"type": "string", "description": "Text to type or key to press"},
                        "reason": {"type": "string"}
                    },
                    "required": ["verdict"]
                }
            })

            # Inject edit_image tool for programmatic image editing via Pillow + Vision
            # Uses LLM vision to analyze the image, locate objects, then draw on them
            tools_payload.append({
                "name": "edit_image",
                "description": (
                    "Edit an image file using vision-guided drawing. "
                    "First analyzes the image with AI vision to locate objects, then performs drawing operations. "
                    "Provide a 'query' describing what to find/do (e.g. 'find the black rectangle and draw a red circle above it'). "
                    "The tool will use AI vision to identify object positions and compute pixel coordinates automatically. "
                    "You can also provide explicit 'operations' if you already know the coordinates. "
                    "Use this instead of trying to launch GIMP/KolourPaint."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Absolute path to the image file to edit"},
                        "query": {
                            "type": "string",
                            "description": (
                                "Natural language description of what to do. The tool will use AI vision to analyze the image, "
                                "locate objects, and determine coordinates. Example: 'Draw a red circle above the black rectangle'"
                            )
                        },
                        "operations": {
                            "type": "array",
                            "description": "Optional explicit operations (if you already know coordinates). If 'query' is provided, these are ignored and the tool auto-generates operations from vision analysis.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "enum": ["draw_circle", "draw_rectangle", "draw_line", "draw_text", "resize", "crop", "rotate", "blur", "brightness"]},
                                    "x": {"type": "integer"}, "y": {"type": "integer"},
                                    "width": {"type": "integer"}, "height": {"type": "integer"},
                                    "radius": {"type": "integer"},
                                    "color": {"type": "string"},
                                    "outline": {"type": "string"},
                                    "fill": {"type": "string"},
                                    "line_width": {"type": "integer"},
                                    "text": {"type": "string"},
                                    "font_size": {"type": "integer"},
                                    "x2": {"type": "integer"}, "y2": {"type": "integer"},
                                    "angle": {"type": "number"},
                                    "factor": {"type": "number"}
                                },
                                "required": ["type"]
                            }
                        },
                        "save_path": {"type": "string", "description": "Path to save result (defaults to overwriting the input file)"}
                    },
                    "required": ["file_path"]
                }
            })

        if not tools_payload:
            return await _chat(messages=messages, tools=None,
                               agent=agent, session_id=session_id,
                               provider_pin=provider_pin,
                               max_tokens=max_tokens, temperature=temperature)


        from pathlib import Path
        trajectory_dir = Path("trajectories") / session_id

        has_scanned_since_last_action = False
        action_pending_verification = False
        save_verified = False          # Trap 8 Guard: blocks kill_app until ctrl+s is executed and verified
        last_action_was_save = False    # Tracks whether the most recent action was ctrl+s
        consecutive_errors = 0
        turn_index = 1
        
        # Infinite loop guard: detect repeated identical tool calls
        from collections import deque, Counter
        recent_calls = deque(maxlen=6)  # Track last 6 calls
        tool_call_counter = Counter()  # Track total calls per tool name

        def _log_violation(violation_type: str, detail: str):
            """Log an architecture violation as a trajectory turn for debugging."""
            nonlocal turn_index
            try:
                import json, time
                viol_dir = trajectory_dir / f"turn-{turn_index:05d}"
                viol_dir.mkdir(parents=True, exist_ok=True)
                violation_data = {
                    "tool": "__architecture_violation__",
                    "violation_type": violation_type,
                    "detail": detail,
                    "timestamp": str(time.time()),
                    "action_pending_verification": action_pending_verification,
                    "save_verified": save_verified,
                }
                with open(viol_dir / "action.json", "w") as f:
                    json.dump(violation_data, f, indent=2)
                turn_index += 1
            except Exception as e:
                print(f"DEBUG: Failed to log violation trajectory: {e}")

        try:
            hop_count = 0
            for _ in range(MAX_TOOL_HOPS + 1):
                hop_count += 1
                
                # Inject budget warnings when hops are running low and save hasn't happened
                remaining = MAX_TOOL_HOPS - hop_count
                if not save_verified and remaining in (50, 20, 10):
                    messages.append({
                        "role": "user",
                        "content": f"⚠️ BUDGET WARNING: You have only {remaining} tool calls remaining and save_verified=False. "
                                   f"You MUST save the file NOW with ctrl+s before you run out of tool calls, "
                                   f"or ALL your work will be LOST. Save immediately, then continue."
                    })
                
                reply = await _chat(messages=messages, tools=tools_payload,
                                    agent=agent, session_id=session_id,
                                    provider_pin=provider_pin,
                                    max_tokens=max_tokens, temperature=temperature)
                last_reply = reply
                tool_calls = reply.get("tool_calls") or []
                if not tool_calls:
                    if action_pending_verification:
                        messages.append({
                            "role": "user",
                            "content": "ERROR: Architecture Violation. You completed your turn without verifying your last action! You MUST call get_window_state to verify the result of your last action before concluding."
                        })
                        continue
                    return reply
                
                # Carry the assistant's tool-call turn back through.

                messages.append({
                    "role": "assistant",
                    "content": reply.get("text", "") or "",
                    "tool_calls": copy.deepcopy(tool_calls),
                })
                
                acted_this_turn = False
                for tc in tool_calls:
                    tc_name = tc["name"]
                    tc_args = tc.get("arguments") or {}
                    print(f"DEBUG: LLM called tool: {tc_name} with args: {tc_args}")
                    
                    # Infinite loop guard: two-level detection
                    # Level 1: exact match (same tool + same args) — 4 repeats
                    call_sig = f"{tc_name}:{json.dumps(tc_args, sort_keys=True)[:200]}"
                    recent_calls.append(call_sig)
                    if len(recent_calls) >= 4 and len(set(list(recent_calls)[-4:])) == 1:
                        loop_msg = (f"ERROR: INFINITE LOOP DETECTED. You have called '{tc_name}' with identical arguments "
                                   f"4 times in a row. This tool is failing repeatedly. STOP calling it. "
                                   f"Try a completely different approach or report that the task cannot be completed.")
                        print(f"[LOOP GUARD] Breaking exact-match loop on: {tc_name}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": loop_msg
                        })
                        continue
                    # Level 2: same tool called too many times total (catches alternating patterns)
                    # e.g. launch_app → list_apps → get_accessibility_tree → launch_app → ...
                    tool_call_counter[tc_name] += 1
                    if tool_call_counter[tc_name] >= 8 and tc_name in ("launch_app",):
                        loop_msg = (f"ERROR: TOOL LOOP DETECTED. You have called '{tc_name}' "
                                   f"{tool_call_counter[tc_name]} times but it keeps failing. "
                                   f"This application is NOT available in this environment. "
                                   f"STOP trying to launch it. Use a programmatic approach instead "
                                   f"(e.g. edit_image for images, coder/sandbox_executor for code tasks). "
                                   f"If the task requires a specific application that is not installed, "
                                   f"report that the task cannot be completed.")
                        print(f"[LOOP GUARD] Breaking counter loop on: {tc_name} ({tool_call_counter[tc_name]} calls)")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": loop_msg
                        })
                        continue
                    
                    if action_pending_verification and tc_name not in ("get_window_state", "get_accessibility_tree"):
                        violation_msg = f"ERROR: Architecture Violation (scan_act_verify). You called '{tc_name}' without verifying your last action. You MUST call get_window_state immediately after an action to verify its outcome before calling any other tools."
                        _log_violation("scan_act_verify", f"Agent tried to call '{tc_name}' with action_pending_verification=True")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": violation_msg
                        })
                        continue

                    # Proactive Guard against Trap 4: Cache Misses (UI Reflow)
                    if tc_name in ("get_window_state", "get_accessibility_tree"):
                        has_scanned_since_last_action = True
                        # Trap 8 Guard: If the previous action was ctrl+s and we just verified, mark save as done
                        if last_action_was_save:
                            save_verified = True
                            last_action_was_save = False
                        action_pending_verification = False
                        consecutive_errors = 0  # successful scan resets error threshold
                    elif tc_name == "edit_image":
                        # Handle vision-guided image editing via Pillow + browser skill's vision layer
                        # Uses the same V9 /v1/vision pipeline as the Set-of-Marks driver
                        args = tc.get("arguments") or {}
                        file_path = args.get("file_path", "")
                        query = args.get("query", "")
                        operations = args.get("operations", [])
                        save_path = args.get("save_path", "") or file_path
                        
                        try:
                            from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
                            import base64, io
                            img = Image.open(file_path)
                            img_w, img_h = img.size
                            
                            # If query is provided, use browser skill's vision layer to analyze
                            if query and not operations:
                                print(f"[edit_image] Vision analysis via V9Client: {query}")
                                # Convert image to base64 data URL (same format as SoM driver)
                                buf = io.BytesIO()
                                img_format = "JPEG" if file_path.lower().endswith((".jpg", ".jpeg")) else "PNG"
                                img.save(buf, format=img_format)
                                img_b64 = base64.b64encode(buf.getvalue()).decode()
                                img_data_url = f"data:image/{img_format.lower()};base64,{img_b64}"
                                
                                # Structured schema for vision response (same pattern as browser driver)
                                ops_schema = {
                                    "type": "object",
                                    "properties": {
                                        "analysis": {"type": "string", "description": "Brief description of objects found"},
                                        "operations": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "type": {"type": "string", "enum": ["draw_circle", "draw_rectangle", "draw_line", "draw_text"]},
                                                    "x": {"type": "integer"}, "y": {"type": "integer"},
                                                    "x2": {"type": "integer"}, "y2": {"type": "integer"},
                                                    "radius": {"type": "integer"},
                                                    "color": {"type": "string"},
                                                    "fill": {"type": "string"},
                                                    "line_width": {"type": "integer"},
                                                    "text": {"type": "string"},
                                                    "font_size": {"type": "integer"}
                                                },
                                                "required": ["type", "x", "y"]
                                            }
                                        }
                                    },
                                    "required": ["analysis", "operations"]
                                }
                                
                                vision_prompt = (
                                    f"You are an image analysis and editing assistant. The image is {img_w}x{img_h} pixels.\n"
                                    f"Task: {query}\n\n"
                                    f"Analyze the image carefully:\n"
                                    f"1. Identify ALL visible objects, shapes, and their pixel positions\n"
                                    f"2. Determine the bounding boxes of key objects\n"
                                    f"3. Compute the exact pixel coordinates for the requested drawing operations\n\n"
                                    f"Coordinate system: (0,0) is top-left. X increases right, Y increases down.\n"
                                    f"For circles: x,y = center point. For rectangles: x,y = top-left, x2,y2 = bottom-right.\n"
                                    f"For lines: x,y = start, x2,y2 = end.\n\n"
                                    f"Return your analysis and the operations to perform."
                                )
                                
                                # Use V9Client — same async vision client as browser Set-of-Marks driver
                                from browser.client import V9Client
                                v9 = V9Client(base_url="http://localhost:8109", agent="edit_image")
                                v_result = await v9.vision(
                                    image_data_url=img_data_url,
                                    prompt=vision_prompt,
                                    schema=ops_schema,
                                    schema_name="ImageEditOps",
                                    max_tokens=1024
                                )
                                
                                print(f"[edit_image] Vision analysis: {v_result.text[:300]}")
                                
                                # Extract operations from structured response
                                if v_result.parsed and "operations" in v_result.parsed:
                                    operations = v_result.parsed["operations"]
                                    analysis = v_result.parsed.get("analysis", "")
                                    print(f"[edit_image] Analysis: {analysis}")
                                    print(f"[edit_image] Got {len(operations)} operations from vision")
                                else:
                                    # Fallback: try to parse JSON from raw text
                                    import re as _re
                                    json_match = _re.search(r'\[.*\]', v_result.text, _re.DOTALL)
                                    if json_match:
                                        operations = json.loads(json_match.group())
                                    else:
                                        raise ValueError(f"Vision returned no parseable operations: {v_result.text[:200]}")
                            
                            # Execute operations
                            draw = ImageDraw.Draw(img)
                            applied = []
                            
                            for op in operations:
                                op_type = op.get("type", "")
                                color = op.get("color", "red")
                                outline = op.get("outline", color)
                                fill = op.get("fill", "")
                                lw = op.get("line_width", 3)
                                
                                if op_type == "draw_circle":
                                    cx, cy = op.get("x", img_w//2), op.get("y", img_h//2)
                                    r = op.get("radius", 50)
                                    bbox = [cx - r, cy - r, cx + r, cy + r]
                                    draw.ellipse(bbox, fill=fill or None, outline=outline, width=lw)
                                    applied.append(f"circle at ({cx},{cy}) r={r} color={outline}")
                                
                                elif op_type == "draw_rectangle":
                                    x1, y1 = op.get("x", 0), op.get("y", 0)
                                    x2 = op.get("x2", x1 + op.get("width", 100))
                                    y2 = op.get("y2", y1 + op.get("height", 100))
                                    draw.rectangle([x1, y1, x2, y2], fill=fill or None, outline=outline, width=lw)
                                    applied.append(f"rectangle ({x1},{y1})-({x2},{y2}) color={outline}")
                                
                                elif op_type == "draw_line":
                                    x1, y1 = op.get("x", 0), op.get("y", 0)
                                    x2, y2 = op.get("x2", img_w), op.get("y2", img_h)
                                    draw.line([x1, y1, x2, y2], fill=color, width=lw)
                                    applied.append(f"line ({x1},{y1})-({x2},{y2}) color={color}")
                                
                                elif op_type == "draw_text":
                                    x, y = op.get("x", 10), op.get("y", 10)
                                    text = op.get("text", "")
                                    fs = op.get("font_size", 24)
                                    try:
                                        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", fs)
                                    except Exception:
                                        font = ImageFont.load_default()
                                    draw.text((x, y), text, fill=color, font=font)
                                    applied.append(f"text '{text}' at ({x},{y}) size={fs}")
                                
                                elif op_type == "resize":
                                    w = op.get("width", img_w)
                                    h = op.get("height", img_h)
                                    img = img.resize((w, h), Image.LANCZOS)
                                    draw = ImageDraw.Draw(img)
                                    applied.append(f"resize to {w}x{h}")
                                
                                elif op_type == "crop":
                                    x1, y1 = op.get("x", 0), op.get("y", 0)
                                    x2, y2 = op.get("x2", img_w), op.get("y2", img_h)
                                    img = img.crop((x1, y1, x2, y2))
                                    draw = ImageDraw.Draw(img)
                                    applied.append(f"crop ({x1},{y1})-({x2},{y2})")
                                
                                elif op_type == "rotate":
                                    angle = op.get("angle", 90)
                                    img = img.rotate(angle, expand=True)
                                    draw = ImageDraw.Draw(img)
                                    applied.append(f"rotate {angle} deg")
                                
                                elif op_type == "blur":
                                    r = op.get("radius", 2)
                                    img = img.filter(ImageFilter.GaussianBlur(radius=r))
                                    draw = ImageDraw.Draw(img)
                                    applied.append(f"blur r={r}")
                                
                                elif op_type == "brightness":
                                    factor = op.get("factor", 1.2)
                                    img = ImageEnhance.Brightness(img).enhance(factor)
                                    draw = ImageDraw.Draw(img)
                                    applied.append(f"brightness x{factor}")
                                
                                else:
                                    applied.append(f"UNKNOWN op: {op_type}")
                            
                            img.save(save_path)
                            vision_note = " (coordinates from AI vision analysis)" if query else ""
                            result_text = f"SUCCESS: Image saved to {save_path} ({img.size[0]}x{img.size[1]}){vision_note}. Applied: {', '.join(applied)}"
                        except Exception as e:
                            import traceback
                            result_text = f"ERROR: edit_image failed: {e}\n{traceback.format_exc()}"
                        
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": result_text,
                        })
                        continue
                    elif tc_name == "desktop_judgment":
                        args = tc.get("arguments") or {}
                        verdict = args.get("verdict")
                        
                        if verdict == "escalate":
                            # Route directly to Layer 5 Vision Fallback
                            if getattr(mux, "last_image_data", None):
                                from gateway import LLM
                                vision_llm = LLM("gemini")
                                try:
                                    print(f"[Layer 2b -> Layer 5] Agent escalated. Routing to Vision Fallback...")
                                    v_res = await vision_llm.vision(
                                        prompt=f"The agent escalated with reason: {args.get('reason', 'None')}. Look at the screenshot. Identify the primary interactive elements. Return their (X, Y) coordinates.",
                                        image_data_url=mux.last_image_data,
                                        max_tokens=150
                                    )
                                    result_text = f"Layer 2b Escalated to Vision. Verdict: {v_res.get('text', 'No verdict')}"
                                except Exception as e:
                                    result_text = f"Layer 2b Escalated. Vision fallback failed: {e}"
                            else:
                                result_text = "Layer 2b Escalated, but no screenshot available for vision fallback."
                            
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.get("id", ""),
                                "content": result_text,
                            })
                            continue
                            
                        elif verdict == "act":
                            # Route to the appropriate action
                            action_type = args.get("action_type")
                            if not action_type:
                                messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": "error: action_type required for 'act' verdict"})
                                continue
                                
                            # Construct a sub-tool call and route it
                            act_args = {}
                            if "element_index" in args:
                                act_args["element_index"] = args["element_index"]
                            if action_type == "type_text" and "action_value" in args:
                                act_args["text"] = args["action_value"]
                            elif action_type in ("press_key", "hotkey") and "action_value" in args:
                                act_args["key"] = args["action_value"]
                                
                            # Override tc_name and args so the dispatch below handles it!
                            tc_name = action_type
                            tc["arguments"] = act_args
                            # Intentionally fall through so the standard `tc_name in ("click", ...)` handles it!
                        else:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.get("id", ""),
                                "content": "ERROR: Invalid or missing 'verdict' in desktop_judgment. You MUST provide 'verdict': 'act' and include 'action_type' and 'action_value'."
                            })
                            continue
                                               # Handle the actual action (which may have been routed from desktop_judgment)
                    if tc_name in ("click", "type_text", "press_key", "hotkey", "get_element_center"):
                        if acted_this_turn:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.get("id", ""),
                                "content": "ERROR: You cannot emit multiple actions in parallel within the same turn. Only the first action was executed. You must wait for the response and re-scan."
                            })
                            continue
                            
                        acted_this_turn = True
                        
                        if not has_scanned_since_last_action:
                            # Layer 4 Error Recovery (State Carry-Over Knob)
                            consecutive_errors += 1
                            result_text = (
                                f"ERROR: StaleStateError. You attempted an element-indexed action ({tc_name}) without scanning first! "
                                "UI reflows cause indices to shift. You MUST call get_window_state before ANY action to get fresh indices. "
                            )
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.get("id", ""),
                                "content": result_text,
                            })
                            
                            # Layer 5 Vision Fallback Trigger (StaleState threshold)
                            # Wait until 3 consecutive errors to avoid triggering on a simple parallel-call accident
                            if consecutive_errors >= 3 and getattr(mux, "last_image_data", None):
                                from gateway import LLM
                                vision_llm = LLM("gemini")
                                try:
                                    print("[Vision Fallback] StaleStateError threshold reached. Escalating to Vision layer...")
                                    v_res = await vision_llm.vision(
                                        prompt="The agent is struggling to find the correct element or index. Look at the Set-of-Marks screenshot. Return ONLY the numeric [index] of the most likely element the user wants to interact with next. If you cannot find it, return the (X, Y) coordinates of the target.",
                                        image_data_url=mux.last_image_data,
                                        max_tokens=100
                                    )
                                    messages[-1]["content"] += f"\n\n[Vision Fallback Escalation Verdict]: The Vision model analyzed the screen and suggests using: {v_res.get('text', 'No verdict')}"
                                    consecutive_errors = 0 # reset after fallback
                                except Exception as e:
                                    messages[-1]["content"] += f"\n\n[Vision Fallback Failed]: {e}"
                                    
                            continue  # Skip execution
                            
                        # Force a rescan for any subsequent actions
                        has_scanned_since_last_action = False
                        action_pending_verification = True
                        
                        # Trap 8 Guard: Track if this action was ctrl+s
                        routed_key = (tc.get("arguments") or {}).get("key", "") or (tc.get("arguments") or {}).get("action_value", "")
                        if "ctrl+s" in routed_key.lower():
                            last_action_was_save = True
                        
                    tc_args = tc.get("arguments") or {}
                    
                    # Trap 5 Guard: Electron/Browser/WebKit Apps (Auto-inject debugging port for Linux)
                    if tc_name == "launch_app":
                        app_str = tc_args.get("name") or tc_args.get("launch_path") or ""
                        # Browsers also support CDP/remote-debugging
                        cdp_apps = ["code", "vscode", "slack", "discord", "notion", "obsidian", "chrome", "chromium", "firefox"]
                        is_cdp_app = any(e in app_str.lower() for e in cdp_apps)
                        
                        if is_cdp_app or "electron_debugging_port" in tc_args:
                            port = tc_args.pop("electron_debugging_port", 9222)
                            flag = f" --remote-debugging-port={port}"
                            if "name" in tc_args and "--remote-debugging-port" not in tc_args["name"]:
                                tc_args["name"] += flag
                            if "launch_path" in tc_args and "--remote-debugging-port" not in tc_args["launch_path"]:
                                tc_args["launch_path"] += flag
                                
                        if "webkit_inspector_port" in tc_args:
                            port = tc_args.pop("webkit_inspector_port", 9222)
                            env_prefix = f"WEBKIT_INSPECTOR_SERVER=127.0.0.1:{port} "
                            if "name" in tc_args and "WEBKIT_INSPECTOR_SERVER" not in tc_args["name"]:
                                tc_args["name"] = env_prefix + tc_args["name"]
                            if "launch_path" in tc_args and "WEBKIT_INSPECTOR_SERVER" not in tc_args["launch_path"]:
                                tc_args["launch_path"] = env_prefix + tc_args["launch_path"]

                        # Inject LibreOffice flags before execution
                        if tc_name == "launch_app":
                            app_name = tc_args.get("name") or tc_args.get("launch_path") or ""
                            # Remove literal quotes which cua-driver may mishandle
                            app_name = app_name.replace('"', '').replace("'", "")
                            
                            # Intercept xdg-open for .ods/.ods files → rewrite to libreoffice direct
                            urls = tc_args.get("urls") or []
                            if urls and any(u.endswith((".ods", ".xlsx", ".xls", ".csv")) for u in urls):
                                # Agent tried to open via xdg-open; rewrite to direct libreoffice
                                file_path = urls[0]
                                if file_path.startswith("file://"):
                                    file_path = file_path[7:]  # strip file:// prefix
                                app_name = f"libreoffice --norestore --calc {file_path}"
                                tc_args.pop("urls", None)
                                tc_args["name"] = app_name
                            
                            if "libreoffice" in app_name.lower() and "--norestore" not in app_name:
                                app_name = app_name.replace("libreoffice", "libreoffice --norestore")
                            if "name" in tc_args: tc_args["name"] = app_name
                            if "launch_path" in tc_args: tc_args["launch_path"] = app_name

                    if tc_name == "type_text":
                        text = tc_args.get("text", "")
                        if text:


                            # Give the window a moment to be ready if it was just focused
                            time.sleep(0.5)
                            try:
                                # Use xdotool which injects XTEST events, reliably bypassing GTK4's XSendEvent block
                                subprocess.run(["xdotool", "type", "--delay", "50", text], check=True)
                                result_text = f"Successfully typed: {text}"
                            except Exception as e:
                                result_text = f"Failed to type using xdotool: {e}"
                        else:
                            result_text = "Error: text argument missing for type_text"
                    elif tc_name in ("press_key", "hotkey"):
                        key = tc_args.get("key", "")
                        if key:


                            time.sleep(0.5)
                            try:
                                key = key.replace("page down", "page_down").replace("page up", "page_up")
                                seq_parts = key.split(' ')
                                for seq in seq_parts:
                                    if not seq.strip(): continue
                                    parts = seq.split('+')
                                    mapped_parts = []
                                    for p in parts:
                                        pl = p.strip().lower()
                                        if pl in ('escape', 'esc'): mapped_parts.append('Escape')
                                        elif pl in ('enter', 'return'): mapped_parts.append('Return')
                                        elif pl == 'space': mapped_parts.append('space')
                                        elif pl == 'tab': mapped_parts.append('Tab')
                                        elif pl == 'up': mapped_parts.append('Up')
                                        elif pl == 'down': mapped_parts.append('Down')
                                        elif pl == 'left': mapped_parts.append('Left')
                                        elif pl == 'right': mapped_parts.append('Right')
                                        elif pl == 'home': mapped_parts.append('Home')
                                        elif pl == 'end': mapped_parts.append('End')
                                        elif pl in ('page_down', 'pagedown', 'pgdn'): mapped_parts.append('Page_Down')
                                        elif pl in ('page_up', 'pageup', 'pgup'): mapped_parts.append('Page_Up')
                                        elif re.match(r'^f\d+$', pl): mapped_parts.append(pl.upper())
                                        else: mapped_parts.append(p.strip())
                                    xdotool_args = ["xdotool", "key", "--delay", "50", '+'.join(mapped_parts)]
                                    subprocess.run(xdotool_args, check=True)
                                    time.sleep(0.8)
                                result_text = f"Successfully pressed key sequence: {key}"
                                
                                # Trap 10: LibreOffice "Keep Current Format?" Dialog
                                # When saving ODS files, LibreOffice may show a confirmation dialog
                                # that the blind agent cannot see (AT-SPI returns elements=1).
                                # Automatically press Enter after ctrl+s to dismiss it.
                                if "ctrl+s" in key.lower():
                                    time.sleep(1.5)  # Wait for the dialog to appear
                                    subprocess.run(["xdotool", "key", "Return"], check=False)
                                    time.sleep(1.0)  # Wait for save to complete
                                    result_text += " [Auto-dismissed potential format dialog with Enter]"
                            except Exception as e:
                                result_text = f"Failed to press key using xdotool: {e}"
                        else:
                            result_text = f"Error: key argument missing for {tc_name}"
                    else:
                        if tc_name == "kill_app":
                            # Trap 8 Guard: Block kill_app if save was never verified
                            if not save_verified:
                                violation_msg = (
                                    "ERROR: Architecture Violation (save_before_kill). You attempted to kill the application "
                                    "without saving first! You MUST press ctrl+s, then call get_window_state to verify "
                                    "the save completed, BEFORE calling kill_app. The file will be lost otherwise."
                                )
                                _log_violation("save_before_kill", f"kill_app called with save_verified=False, pid={tc_args.get('pid')}")
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tc.get("id", ""),
                                    "content": violation_msg,
                                })
                                continue

                            time.sleep(2)
                            try:

                                for lock_file in glob.glob("/home/acer/Documents/DEEPAK/eva_april2026/mainbranch/eva_april2026/week10/data/.~lock.*#"):
                                    os.remove(lock_file)
                            except:
                                pass
                        if tc_name == "launch_app":
                            app_name = tc_args.get("name") or tc_args.get("launch_path") or ""
                            
                            # Intercept vscode/code to use cursor, and parse manual --remote-debugging-port args
                            if "code" in app_name.lower() or "cursor" in app_name.lower():
                                tc_args["name"] = "cursor"
                                
                                # If the agent passed a full command line with the port, extract it
                                if "--remote-debugging-port=" in app_name:
                                    try:
                                        port_str = app_name.split("--remote-debugging-port=")[1].split()[0]
                                        tc_args["electron_debugging_port"] = int(port_str)
                                    except:
                                        pass
                                        
                                result_text = await mux.call_tool(tc_name, tc_args)
                            elif " " in app_name:
                                import shlex
                                try:
                                    args = shlex.split(app_name)
                                    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                                    result_text = f"Successfully launched {args[0]} via subprocess."
                                except Exception as e:
                                    result_text = f"Failed to launch via subprocess: {e}"
                            else:
                                result_text = await mux.call_tool(tc_name, tc_args)
                        else:
                            result_text = await mux.call_tool(tc_name, tc_args)
                    
                    # Layer 2: Perception Interpretation (Apply filtering)
                    if tc_name in ("get_window_state", "get_accessibility_tree"):
                        query_passed = "query" in tc_args
                        result_text = await condense_perception(result_text, query_passed)
                    
                    # Guard against Trap 2: Background Launch
                    if tc["name"] == "launch_app":



                        
                        args = tc.get("arguments") or {}
                        app_name = args.get("name") or args.get("launch_path") or ""
                        if app_name:
                            # Extract the base name if a full path is provided
                            short_name = app_name.split('/')[-1]
                            if platform.system() == "Darwin":
                                try:
                                    subprocess.run(["osascript", "-e", f'tell application "{short_name}" to activate'], check=False)
                                except Exception:
                                    pass
                            elif platform.system() == "Linux":
                                try:
                                    subprocess.run(["wmctrl", "-a", short_name], check=False)
                                except Exception:
                                    pass
                            time.sleep(0.5)
                    
                    # Guard against Trap 1, 2, 3, 5, 6: Empty AX Tree
                    if tc_name in ("get_window_state", "get_accessibility_tree"):
                        if "elements=0" in result_text:
                            # Guard Trap 6: Game/Canvas Apps (Escalate to Layer 5 Vision)
                            canvas_apps = ["figma", "photopea", "blender", "steam", "minecraft", "roblox", "unity", "unreal", "godot", "game"]
                            if any(c in result_text.lower() for c in canvas_apps):
                                if getattr(mux, "last_image_data", None):
                                    from gateway import LLM
                                    vision_llm = LLM("gemini")
                                    try:
                                        print(f"[Vision Fallback] Canvas app detected. Escalating to Vision layer...")
                                        v_res = await vision_llm.vision(
                                            prompt="This is a Canvas/OpenGL application so there is no DOM/Accessibility tree. Look at the screenshot. Identify the primary interactive elements. Return their (X, Y) coordinates so I can click them.",
                                            image_data_url=mux.last_image_data,
                                            max_tokens=150
                                        )
                                        result_text = f"AX Tree is empty (Canvas App). Escalated to Vision. Verdict: {v_res.get('text', 'No verdict')}"
                                    except Exception as e:
                                        result_text = f"AX Tree empty. Vision escalation failed: {e}"
                                else:
                                    result_text = "AX Tree is empty (Canvas App). Vision escalation failed (No screenshot available)."
                            else:

                                if platform.system() == "Darwin":
                                    perm_msg = "macOS: Run `cua-driver permissions grant` (accept Accessibility and Screen Recording TCCs). Do NOT grant via terminal."
                                else:
                                    perm_msg = "Linux: Default to X11 (Wayland requires interactive portal grants)."
                                    
                                raise PermissionsError(
                                    f"cua-driver returned an empty AX tree (element_count: 0).\n"
                                    f"Possible Traps:\n"
                                    f"1. Permissions missing -> {perm_msg}\n"
                                    f"2. App launched in background -> Use bring_to_front, sleep, and re-scan.\n"
                                    f"3. Qt App -> Relaunch with QT_ACCESSIBILITY=1.\n"
                                    f"4. Electron App -> Opaque AXWebArea. Relaunch with --remote-debugging-port and use web tools.\n"
                                    f"5. Game/Canvas -> No AX nodes exist. Escalate to Layer 3 Vision tools."
                                )
                        # Guard: Blind Window (elements=1 with only a window frame)
                        # cua-driver v0.5.7 has a bug where it doesn't traverse GTK3's
                        # ATK bridge for LibreOffice. Native python3-gi AT-SPI CAN see
                        # the full tree. Use native_atspi.py as fallback.
                        elif "elements=1" in result_text and tc_name == "get_window_state":
                            import re
                            elem_lines = [l for l in result_text.splitlines() if re.search(r'\[\d+\]', l)]
                            if len(elem_lines) <= 1:
                                # Try native AT-SPI fallback
                                scan_pid = tc_args.get("pid")
                                native_result = None
                                if scan_pid:
                                    try:

                                        native_script = str(Path(__file__).parent / "native_atspi.py")
                                        env_copy = os.environ.copy()
                                        env_copy["DISPLAY"] = env_copy.get("DISPLAY", ":99")
                                        env_copy.setdefault("GNOME_ACCESSIBILITY", "1")
                                        env_copy.setdefault("GTK_MODULES", "gail:atk-bridge")
                                        if "DBUS_SESSION_BUS_ADDRESS" not in env_copy:
                                            try:
                                                with open("/tmp/dbus-session-address") as f:
                                                    dbus_addr = f.read().strip()
                                                if dbus_addr:
                                                    env_copy["DBUS_SESSION_BUS_ADDRESS"] = dbus_addr
                                                    print(f"[NATIVE AT-SPI] Using DBUS: {dbus_addr}")
                                            except FileNotFoundError:
                                                print("[NATIVE AT-SPI] WARNING: /tmp/dbus-session-address not found")
                                        # Also pass AT-SPI bus address (separate from session bus!)
                                        try:
                                            with open("/tmp/at-spi-bus-address") as f:
                                                atspi_addr = f.read().strip()
                                            if atspi_addr:
                                                env_copy["AT_SPI_BUS_ADDRESS"] = atspi_addr
                                                print(f"[NATIVE AT-SPI] Using AT-SPI bus: {atspi_addr}")
                                        except FileNotFoundError:
                                            pass
                                        # Must use /usr/bin/python3 (system Python) since python3-gi
                                        # is a system apt package not visible to the uv virtualenv
                                        system_python = "/usr/bin/python3"
                                        proc = subprocess.run(
                                            [system_python, native_script, str(scan_pid)],
                                            capture_output=True, text=True, timeout=20,
                                            env=env_copy,
                                        )
                                        if proc.returncode == 0 and "NATIVE AT-SPI SCAN" in proc.stdout:
                                            native_result = proc.stdout.strip()
                                            print(f"[NATIVE AT-SPI] Fallback succeeded for PID {scan_pid}")
                                        else:
                                            err_detail = proc.stderr.strip() or proc.stdout.strip()
                                            print(f"[NATIVE AT-SPI] Fallback failed (rc={proc.returncode}): {err_detail[:300]}")
                                    except Exception as e:
                                        print(f"[NATIVE AT-SPI] Fallback error: {e}")
                                
                                if native_result:
                                    result_text = native_result
                                else:
                                    result_text += (
                                        "\n\n⚠️ WARNING: BLIND WINDOW DETECTED. The accessibility tree shows only "
                                        "the top-level window frame (elements=1). This means you CANNOT see any "
                                        "dialogs, menus, cells, or buttons inside the application. Your keystrokes "
                                        "may not be landing where you think. Possible causes:\n"
                                        "  - SAL_USE_VCLPLUGIN=gtk3 not set (LibreOffice is not using GTK3 backend)\n"
                                        "  - No window manager running (AT-SPI needs focus management)\n"
                                        "  - The application crashed or a modal dialog is blocking\n"
                                        "You should proceed with caution and save frequently."
                                    )
                    
                    # Guard against Trap 4: Cache Misses
                    if tc["name"] in ("click", "type_text", "press_key", "hotkey", "get_element_center"):
                        result_lower = result_text.lower()
                        if "not found in cache" in result_lower or ("element_index" in result_lower and "not found" in result_lower):
                            # Layer 4 Error Recovery (State Carry-Over Knob):
                            consecutive_errors += 1
                            result_text = (
                                "ERROR: Cache miss on action. The UI reflowed or you used a stale element_index from a previous turn.\n"
                                "Guard: You MUST always re-scan with get_window_state before acting."
                            )
                            
                            # Layer 5 Vision Fallback Trigger (Cache Miss threshold)
                            if consecutive_errors >= 3 and getattr(mux, "last_image_data", None):
                                from gateway import LLM
                                vision_llm = LLM("gemini")
                                try:
                                    print("[Vision Fallback] Cache Miss threshold reached. Escalating to Vision layer...")
                                    v_res = await vision_llm.vision(
                                        prompt="The agent is struggling with a cache miss (UI reflow). Look at the Set-of-Marks screenshot. Return ONLY the numeric [index] of the most likely element the user wants to interact with next. If you cannot find it, return the (X, Y) coordinates.",
                                        image_data_url=mux.last_image_data,
                                        max_tokens=100
                                    )
                                    result_text += f"\n\n[Vision Fallback Escalation Verdict]: The Vision model analyzed the screen and suggests using: {v_res.get('text', 'No verdict')}"
                                    consecutive_errors = 0 # reset after fallback
                                except Exception as e:
                                    result_text += f"\n\n[Vision Fallback Failed]: {e}"
                            
                    # Manual Trajectory Turn Recording (Restore visual turn-folders for debugging)
                    try:
                        turn_dir = trajectory_dir / f"turn-{turn_index:05d}"
                        turn_dir.mkdir(parents=True, exist_ok=True)
                        # json and time are imported at module level (line 37-38)
                        action_data = {
                            "tool": tc_name,
                            "arguments": tc_args,
                            "result_summary": str(result_text)[:500],
                            "timestamp": str(time.time()),
                            "action_pending_verification": action_pending_verification,
                            "save_verified": save_verified
                        }
                        with open(turn_dir / "action.json", "w") as f:
                            json.dump(action_data, f, indent=2)
                        
                        if getattr(mux, "last_image_data", None):
                            import base64
                            img_data = mux.last_image_data.split(",")[1]
                            with open(turn_dir / "screenshot.png", "wb") as f:
                                f.write(base64.b64decode(img_data))
                        
                        turn_index += 1
                    except Exception as e:
                        print(f"DEBUG: Failed to save manual turn trajectory: {e}")

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": result_text[:8_000],  # cap per-tool reply
                    })
        
            # If we reach here, we hit the hop cap without a final text response.
            _log_violation("max_tool_hops_exhausted", f"Agent exhausted {MAX_TOOL_HOPS} tool hops without completing. save_verified={save_verified}, action_pending_verification={action_pending_verification}")
            
            # EMERGENCY FORCED SAVE: If the agent exhausted hops without saving,
            # force a ctrl+s via xdotool to prevent data loss.
            if not save_verified:


                try:
                    print("[EMERGENCY] Agent exhausted hops without saving. Forcing ctrl+s...")
                    subprocess.run(["xdotool", "key", "Escape"], check=False)  # Close any open dialogs first
                    time.sleep(0.5)
                    subprocess.run(["xdotool", "key", "ctrl+s"], check=True)
                    time.sleep(1.5)
                    subprocess.run(["xdotool", "key", "Return"], check=False)  # Dismiss format dialog
                    time.sleep(1.0)
                    print("[EMERGENCY] Forced save completed.")
                    _log_violation("emergency_forced_save", "Forced ctrl+s because agent exhausted hops without saving")
                except Exception as e:
                    print(f"[EMERGENCY] Forced save FAILED: {e}")
                    _log_violation("emergency_forced_save_failed", f"Forced ctrl+s failed: {e}")
            
            # Force the LLM to summarize its findings and output final text.
            messages.append({
                "role": "user",
                "content": f"You have reached the maximum number of allowed tool calls ({MAX_TOOL_HOPS}). WARNING: save_verified={save_verified}. If you did not save, this task FAILED. Please output your final JSON result based on the information you have gathered so far, ensuring it matches the required schema.",
            })
            last_reply = await _chat(messages=messages, tools=None,
                                     agent=agent, session_id=session_id,
                                     provider_pin=provider_pin,
                                     max_tokens=max_tokens, temperature=temperature)
        
            # Dump transcript for debugging.
            try:
                with open("mcp_debug_transcript.json", "w") as f:
                    json.dump(messages, f, indent=2)
            except Exception:
                pass

        except Exception:
            raise

    return last_reply


async def _chat(*, messages, tools, agent, session_id, provider_pin,
                max_tokens, temperature) -> dict:
    import asyncio as _a
    return await _a.to_thread(
        LLM().chat,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        agent=agent,
        session=session_id,
        provider=provider_pin,
        max_tokens=max_tokens,
        temperature=temperature,
    )
