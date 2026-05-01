"""
Lesson D — Talk-to-App (v5: generic dashboard).

One template. Any domain. The LLM composes a dashboard from a catalog of
widgets (stat, badges, checklist, progress_list, ring, pie, bar, line,
sparkline, table, text). Every call produces a dashboard spec — the LLM
picks the tabs, picks the widgets, fills the data.

Run:
    python prompt_to_app.py
"""

from __future__ import annotations

print("\n" + "="*40)
print("--- SCRIPT STARTING ---")
print("="*40 + "\n")

import json
import os
import re
import requests
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

MODEL = "gemini-3.1-flash-lite-preview"
HERE = Path(__file__).parent
GENERATED = HERE / "generated_app.py"

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
fin_api_key = os.getenv("FINEDGE_API_KEY")

def get_ticker_finance(ticker: str = "RELIANCE") -> str:
    """
    Fetches financial statement data (P&L) for a given stock ticker.
    Checks local storage first, otherwise calls the API.
    Returns a JSON string containing the financial data.
    """
    print(f"  [tool] get_ticker_finance(ticker={ticker!r})")
    
    # Check local storage first
    filename = HERE / f"{ticker}_finance.json"
    if filename.exists():
        print(f"    → reading {ticker} data from local file: {filename.name}")
        return filename.read_text(encoding="utf-8")

    fin_api_key = os.getenv("FINEDGE_API_KEY")
    if not fin_api_key:
        return "Error: FINEDGE_API_KEY not found in environment."

    url = (
        f"https://data.finedgeapi.com/api/v1/financials/{ticker}"
        f"?statement_type=s&statement_code=pl&period=annual&token={fin_api_key}"
    )
    headers = {'Accept': 'application/json'}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        # Save to local storage for future use
        filename.write_text(json.dumps(data, indent=4), encoding="utf-8")
        print(f"    → fetched and saved {ticker} data to local file: {filename.name}")

        return json.dumps(data)
    except Exception as e:
        return f"Error fetching financial data for {ticker}: {e}"

def get_ticker_ratios(ticker: str = "RELIANCE") -> str:
    """
    Fetches financial ratios for a given stock ticker.
    Checks local storage first, otherwise calls the API.
    Returns a JSON string containing the ratio data.
    """
    print(f"  [tool] get_ticker_ratios(ticker={ticker!r})")
    
    # Check local storage first
    filename = HERE / f"{ticker}_ratios.json"
    if filename.exists():
        print(f"    → reading {ticker} ratios from local file: {filename.name}")
        return filename.read_text(encoding="utf-8")

    fin_api_key = os.getenv("FINEDGE_API_KEY")
    if not fin_api_key:
        return "Error: FINEDGE_API_KEY not found in environment."

    url = (
        f"https://data.finedgeapi.com/api/v1/ratios/{ticker}"
        f"?statement_type=s&ratio_type=pr&token={fin_api_key}"
    )
    headers = {'Accept': 'application/json'}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        # Save to local storage for future use
        filename.write_text(json.dumps(data, indent=4), encoding="utf-8")
        print(f"    → fetched and saved {ticker} ratios to local file: {filename.name}")

        return json.dumps(data)
    except Exception as e:
        return f"Error fetching financial ratios for {ticker}: {e}"

# ---------------------------------------------------------------------------
# Widget renderers. Each returns a list of Python source lines with ZERO
# leading indentation. The dashboard template indents them into place.
# ---------------------------------------------------------------------------

def _slug(s: str, default: str = "k") -> str:
    out = re.sub(r"[^a-zA-Z0-9_]+", "_", str(s)).strip("_").lower()
    return out or default


def _safe(name: str, idx: int, default: str = "item") -> str:
    return _slug(name, default) or f"{default}_{idx}"


def widget_lines(w: dict, ctx: dict) -> list[str]:
    kind = w.get("kind", "")
    ctx["uid"] = ctx.get("uid", 0) + 1
    uid = ctx["uid"]

    if kind == "stat":
        label = w.get("label", "")
        value = str(w.get("value", ""))
        sub = w.get("sub", "")
        out = [
            'with Column(gap=1):',
            f'    Muted({label!r})',
            f'    H1({value!r})',
        ]
        if sub:
            out.append(f'    Muted({sub!r})')
        return out

    if kind == "badges":
        items = w.get("items", [])
        out = ['with Row(gap=2):']
        for it in items:
            lbl = it.get("label", "") if isinstance(it, dict) else str(it)
            var = it.get("variant", "default") if isinstance(it, dict) else "default"
            out.append(f'    Badge({lbl!r}, variant={var!r})')
        return out or ['Muted("(no badges)")']

    if kind == "checklist":
        items = w.get("items", [])
        title = w.get("title")
        out: list[str] = []
        if title:
            out += [f'H3({title!r})']
        out += ['with Column(gap=2):']
        for i, it in enumerate(items):
            label = it.get("label", f"Item {i+1}") if isinstance(it, dict) else str(it)
            out += [
                '    with Row(gap=3):',
                f'        Checkbox(name="cb_{uid}_{i}")',
                f'        Text({label!r})',
            ]
        return out

    if kind == "progress_list":
        items = w.get("items", [])
        title = w.get("title")
        out: list[str] = []
        if title:
            out += [f'H3({title!r})']
        out += ['with Column(gap=3):']
        for it in items:
            if not isinstance(it, dict):
                continue
            label = it.get("label", "")
            val = it.get("value", 0)
            try:
                val = max(0, min(100, int(val)))
            except Exception:
                val = 0
            out += [
                '    with Column(gap=1):',
                f'        Text({label!r})',
                f'        Progress(value={val})',
            ]
        print(out)
        return out

    if kind == "ring":
        label = w.get("label", "")
        value = w.get("value", 0)
        try:
            value = max(0, min(100, int(value)))
        except Exception:
            value = 0
        suffix = w.get("suffix", "%")
        display = f"{value}{suffix}" if suffix else f"{value}"
        out = ['with Column(gap=2):']
        if label:
            out.append(f'    H3({label!r})')
        out.append(f'    Ring(value={value}, label={display!r})')
        return out

    if kind == "pie":
        title = w.get("title", "")
        data = w.get("data", [])
        name_key = w.get("name_key", "name")
        value_key = w.get("value_key", "value")
        # Ensure data is list of dicts with those keys.
        clean = []
        for row in data:
            if isinstance(row, dict) and name_key in row and value_key in row:
                clean.append({name_key: row[name_key], value_key: row[value_key]})
        out = ['with Column(gap=2):']
        if title:
            out.append(f'    H3({title!r})')
        out.append(
            f'    PieChart(data={clean!r}, data_key={value_key!r}, '
            f'name_key={name_key!r}, show_legend=True)'
        )
        return out

    if kind == "bar":
        title = w.get("title", "")
        data = w.get("data", [])
        x_key = w.get("x_key", "x")
        y_keys = w.get("y_keys", ["y"])
        if isinstance(y_keys, str):
            y_keys = [y_keys]
        series_lines = ", ".join(f'ChartSeries(data_key={yk!r}, label={yk!r})' for yk in y_keys)
        out = ['with Column(gap=2):']
        if title:
            out.append(f'    H3({title!r})')
        out += [
            f'    BarChart(data={data!r},',
            f'             series=[{series_lines}],',
            f'             x_axis={x_key!r}, show_legend={len(y_keys) > 1})',
        ]
        return out

    if kind == "line":
        title = w.get("title", "")
        data = w.get("data", [])
        x_key = w.get("x_key", "x")
        y_keys = w.get("y_keys", ["y"])
        if isinstance(y_keys, str):
            y_keys = [y_keys]
        series_lines = ", ".join(f'ChartSeries(data_key={yk!r}, label={yk!r})' for yk in y_keys)
        out = ['with Column(gap=2):']
        if title:
            out.append(f'    H3({title!r})')
        out += [
            f'    LineChart(data={data!r},',
            f'              series=[{series_lines}],',
            f'              x_axis={x_key!r}, show_legend={len(y_keys) > 1})',
        ]
        return out

    if kind == "sparkline":
        values = w.get("values", [])
        title = w.get("title", "")
        out = ['with Column(gap=2):']
        if title:
            out.append(f'    H3({title!r})')
        out.append(f'    Sparkline(data={values!r})')
        return out

    if kind == "table":
        title = w.get("title", "")
        columns = w.get("columns", [])
        rows = w.get("rows", [])
        out = ['with Column(gap=2):']
        if title:
            out.append(f'    H3({title!r})')
        out.append('    with Table():')
        # Header row
        out.append('        with TableHeader():')
        out.append('            with TableRow():')
        for col in columns:
            out.append(f'                TableHead({str(col)!r})')
        # Data rows
        out.append('        with TableBody():')
        for row in rows:
            out.append('            with TableRow():')
            cells = row if isinstance(row, list) else [row.get(c, "") for c in columns]
            for cell in cells:
                out.append(f'                TableCell({str(cell)!r})')
        return out

    if kind == "text":
        heading = w.get("heading", "")
        body = w.get("body", "")
        level = str(w.get("level", "h3")).lower()
        out = ['with Column(gap=1):']
        if heading:
            if level == "h1":
                out.append(f'    H1({heading!r})')
            elif level == "h2":
                out.append(f'    H2({heading!r})')
            else:
                out.append(f'    H3({heading!r})')
        if body:
            out.append(f'    Muted({body!r})')
        return out

    return [f'Muted({f"Unknown widget kind: {kind!r}"!r})']


# ---------------------------------------------------------------------------
# The one template.
# ---------------------------------------------------------------------------

def dashboard(title: str, tabs: list[dict]) -> str:
    # Normalise tabs.
    if not tabs:
        tabs = [{"name": "Main", "widgets": [{"kind": "text", "heading": "Empty dashboard"}]}]

    ctx: dict = {"uid": 0}
    TAB_INDENT = " " * 24          # body of `with Column(gap=5):` at 20 spaces
    WIDGET_SEP = "\n\n" + TAB_INDENT[:-4]  # tiny gap comment not required

    built_tabs: list[tuple[str, str, str]] = []  # (name, value, indented_body)
    for i, tab in enumerate(tabs):
        name = str(tab.get("name") or f"Tab {i+1}")
        value = _slug(tab.get("value") or name, f"tab_{i+1}")
        widgets = tab.get("widgets") or []
        body_lines: list[str] = []
        if not widgets:
            body_lines = [TAB_INDENT + 'Muted("(empty tab)")']
        else:
            for w in widgets:
                for line in widget_lines(w, ctx):
                    body_lines.append((TAB_INDENT + line) if line else "")
        built_tabs.append((name, value, "\n".join(body_lines)))

    first_value = built_tabs[0][1]

    parts = [
        "from prefab_ui.app import PrefabApp",
        "from prefab_ui.components import (",
        "    Badge, Button, Card, CardContent, CardHeader, CardTitle,",
        "    Checkbox, Column, H1, H2, H3, Muted, Progress, Ring, Row,",
        "    Tab, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Tabs, Text,",
        ")",
        "from prefab_ui.components.charts import (",
        "    BarChart, ChartSeries, LineChart, PieChart, Sparkline,",
        ")",
        "",
        'with PrefabApp(css_class="max-w-5xl mx-auto p-6") as app:',
        "    with Card():",
        "        with CardHeader():",
        f"            CardTitle({title!r})",
        "        with CardContent():",
        f"            with Tabs(value={first_value!r}):",
    ]
    for name, value, body in built_tabs:
        parts.append(f'                with Tab({name!r}, value={value!r}):')
        parts.append("                    with Column(gap=5):")
        parts.append(body)
    return "\n".join(parts) + "\n"


TEMPLATES = {"dashboard": dashboard}


# ---------------------------------------------------------------------------
# Planner — one template, full widget catalog, edit-aware.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You design small interactive dashboards. Given the user's sentence
and the CURRENT dashboard spec (if any), respond with the spec for the
dashboard that should be shown next.

TOOL ACCESS:
You have two tools:
1. `get_ticker_finance(ticker: str)`: Use this for P&L data like Revenue, Expenses, Profit.
2. `get_ticker_ratios(ticker: str)`: Use this for financial ratios like PE, ROE, ROCE, Debt-to-Equity, etc.

If the user's request involves a specific company, stock, or financial data, 
YOU MUST CALL THE APPROPRIATE TOOL(S) to get real numbers. 

Once you receive the JSON response from the tool(s):
1. Extract key metrics. 
   - From `get_ticker_finance`: Revenue, Profit, EPS.
   - From `get_ticker_ratios`: PE Ratio, ROE, ROCE, etc.
2. The response contains a list of years. Use the most recent years for your widgets.
3. Use `stat` widgets for current year metrics.
4. Use `line` or `bar` charts for trends over multiple years.
5. Use `table` widgets to show a summary of ratios or P&L over time.
6. Do not invent financial data if the tool can provide it.
7. If the tool returns an error, explain it in a `text` widget.

You have ONE template: `dashboard`. Its spec is:
  {
    "template": "dashboard",
    "params": {
      "title": "<app title>",
      "tabs": [
        { "name": "<tab label>", "widgets": [ ... ] },
        ...
      ]
    }
  }

Each tab's widgets is an ORDERED list. Each widget is one of:

  {"kind": "stat",           "label": "<small label>", "value": "<big text>", "sub": "<optional caption>"}
  {"kind": "badges",         "items": [{"label": "...", "variant": "default|success|warning|destructive"}, ...]}
  {"kind": "checklist",      "title": "<optional>", "items": [{"label": "..."}]}
  {"kind": "progress_list",  "title": "<optional>", "items": [{"label": "...", "value": 0..100}, ...]}
  {"kind": "ring",           "label": "<optional>", "value": 0..100, "suffix": "%"}
  {"kind": "pie",            "title": "<optional>", "data": [{"name": "...", "value": <number>}, ...]}
  {"kind": "bar",            "title": "<optional>", "data": [{"x": "...", "y": <number>, ...}, ...], "x_key": "x", "y_keys": ["y"]}
  {"kind": "line",           "title": "<optional>", "data": [...], "x_key": "x", "y_keys": ["y"] }
  {"kind": "sparkline",      "title": "<optional>", "values": [<number>, ...]}
  {"kind": "table",          "title": "<optional>", "columns": ["Col A", ...], "rows": [["v1","v2",...], ...]}
  {"kind": "text",           "heading": "<optional>", "body": "<optional>", "level": "h1|h2|h3"}

Guidelines:
- Pick tab names that fit the domain (e.g. for a stock tracker: Portfolio, P&L, Watchlist).
- Mix widget kinds — a good tab has a headline stat, some visual (chart/ring), and a list/table.
- Invent realistic-looking sample data (5–8 items usually).
- If the user is MODIFYING the current dashboard, preserve unaffected tabs and widgets.
- For "add a pie chart on the X tab", append or insert a pie widget to that tab.

Respond with EXACTLY ONE JSON object (no prose, no code fences):
  {"template": "dashboard", "params": {...}}
"""


def plan(user_request: str, current_spec: dict | None) -> dict:
    user_prompt = (
        f"Current spec: {json.dumps(current_spec) if current_spec else 'null'}\n"
        f"User request: {user_request}"
    )
    
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name="get_ticker_finance",
                        description="Fetches financial statement data (P&L) for a given stock ticker.",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "ticker": types.Schema(
                                    type="STRING",
                                    description="The stock ticker symbol (e.g., RELIANCE, TCS, AAPL)."
                                )
                            },
                            required=["ticker"]
                        )
                    ),
                    types.FunctionDeclaration(
                        name="get_ticker_ratios",
                        description="Fetches financial ratios for a given stock ticker.",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "ticker": types.Schema(
                                    type="STRING",
                                    description="The stock ticker symbol (e.g., RELIANCE, TCS, AAPL)."
                                )
                            },
                            required=["ticker"]
                        )
                    )
                ]
            )
        ]
    )

    # We use a manual loop to handle tool calls if the model requests them
    response = client.models.generate_content(
        model=MODEL,
        contents=user_prompt,
        config=config
    )

    # Debug: Print response parts to see if there's a function call
    print(f"  [debug] response parts: {response.candidates[0].content.parts}")

    # Check for function calls
    while response.candidates[0].content.parts and response.candidates[0].content.parts[0].function_call:
        call = response.candidates[0].content.parts[0].function_call
        fn_name = call.name
        args = call.args
        
        if fn_name == "get_ticker_finance":
            # Execute the tool
            result = get_ticker_finance(**args)
        elif fn_name == "get_ticker_ratios":
            # Execute the tool
            result = get_ticker_ratios(**args)
        else:
            break

        # Send result back to model
        response = client.models.generate_content(
            model=MODEL,
            contents=[
                types.Content(role="user", parts=[types.Part(text=user_prompt)]),
                response.candidates[0].content,
                types.Content(
                    role="tool",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=fn_name,
                                response={"result": result}
                            )
                        )
                    ]
                )
            ],
            config=config
        )

    raw = (response.text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[1].rsplit("\n", 1)[0]
    return json.loads(raw)


def write_app(spec: dict) -> None:
    name = spec.get("template", "dashboard")
    params = spec.get("params", {})
    if name not in TEMPLATES:
        raise ValueError(f"Unknown template {name!r}.")
    source = TEMPLATES[name](**params)
    compile(source, "<generated_app>", "exec")      # syntax check
    GENERATED.write_text(source, encoding="utf-8")
    os.utime(GENERATED, None)
    print(f"  → wrote {GENERATED.name}")


# ---------------------------------------------------------------------------
# Prefab subprocess + backup/restore.
# ---------------------------------------------------------------------------

def tail_log(log_path: Path, n: int = 30) -> str:
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception as e:
        return f"(could not read log: {e})"


def backup_path() -> Path:
    return HERE / ".last_good_app.py"


def save_backup() -> None:
    if GENERATED.exists():
        backup_path().write_text(GENERATED.read_text(encoding="utf-8"), encoding="utf-8")


def restore_backup() -> bool:
    bp = backup_path()
    if bp.exists():
        GENERATED.write_text(bp.read_text(encoding="utf-8"), encoding="utf-8")
        return True
    return False


class PrefabServer:
    def __init__(self, target: Path, log_path: Path):
        self.target = target
        self.log_path = log_path
        self._proc: subprocess.Popen | None = None
        self._log = None

    def start(self) -> None:
        self._log = open(self.log_path, "a")
        self._log.write("\n===== restart =====\n")
        self._log.flush()
        self._proc = subprocess.Popen(
            ["prefab", "serve", str(self.target)],
            cwd=self.target.parent,
            stdout=self._log,
            stderr=subprocess.STDOUT,
        )

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
            self._proc = None
        if self._log is not None:
            self._log.close()
            self._log = None

    def restart(self) -> None:
        self.stop()
        self.start()


# ---------------------------------------------------------------------------
# REPL.
# ---------------------------------------------------------------------------

def main() -> None:
    print("Talk-to-App v2.0 (with manual tool calling) — describe an app, we'll build it.")
    print("Widget catalog: stat, badges, checklist, progress_list, ring, pie,")
    print("                bar, line, sparkline, table, text")
    print("Type a description, or 'quit' to exit.\n")

    GENERATED.write_text(
        "from prefab_ui.app import PrefabApp\n"
        "from prefab_ui.components import Card, CardContent, CardHeader, CardTitle, Muted\n\n"
        'with PrefabApp(css_class="max-w-md mx-auto p-6") as app:\n'
        "    with Card():\n"
        "        with CardHeader():\n"
        '            CardTitle("Talk-to-App")\n'
        "        with CardContent():\n"
        '            Muted("Waiting for your first prompt in the terminal...")\n',
        encoding="utf-8",
    )

    log_path = HERE / "prefab_server.log"
    log_path.write_text("")
    server = PrefabServer(GENERATED, log_path)
    print(f"Starting Prefab dev server (logs → {log_path.name}) ...")
    server.start()
    time.sleep(1.5)
    print("Open http://127.0.0.1:5175 in your browser.\n")

    current_spec: dict | None = None
    try:
        while True:
            prompt = input("\nWhat do you want to build (or change)? ").strip()
            if not prompt or prompt.lower() in {"quit", "exit"}:
                break
            try:
                spec = plan(prompt, current_spec)
                print(f"  plan: {json.dumps(spec)[:240]}"
                      + ("..." if len(json.dumps(spec)) > 240 else ""))
                save_backup()
                write_app(spec)
                server.restart()
                time.sleep(1.5)
                log_tail = tail_log(log_path, 30)
                looks_broken = (
                    (server._proc and server._proc.poll() is not None)
                    or "traceback" in log_tail.lower()
                    or "exception" in log_tail.lower()
                )
                if looks_broken:
                    print("\n  ✗ Prefab did not come up cleanly.")
                    print("  --- last lines of prefab_server.log ---")
                    print(log_tail)
                    print("  ----------------------------------------")
                    if restore_backup():
                        print("  Reverting to the previous working app...")
                        server.restart()
                        time.sleep(1.0)
                else:
                    current_spec = spec
                    print("  (browser will reconnect in a moment)")
            except Exception as e:
                print(f"  error: {e}")
    except KeyboardInterrupt:
        pass
    finally:
        print("\nShutting down Prefab server...")
        server.stop()


if __name__ == "__main__":
    main()
