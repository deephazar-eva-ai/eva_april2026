import { Renderer } from './renderer.js';

const SYSTEM_PROMPT = `You design small interactive dashboards. Respond with EXACTLY ONE JSON object.
TOOL ACCESS:
1. get_ticker_finance(ticker: str): Use for P&L data like Revenue, Profit.
2. get_ticker_ratios(ticker: str): Use for financial ratios like PE, ROE.
Always use plain ticker symbols without suffixes (e.g., use "RELIANCE" instead of "RELIANCE.NS").

Respond with spec: {"template": "dashboard", "params": {"title": "...", "tabs": [{"name": "...", "widgets": [...]}]}}
Each widget MUST have a "kind" property.
Widget catalog:
- {"kind": "stat", "label": "...", "value": "...", "sub": "..."}
- {"kind": "table", "title": "...", "columns": ["Col A", ...], "rows": [["v1", ...], ...]}
- {"kind": "line", "title": "...", "data": [{"x": "...", "y": ...}], "x_key": "x", "y_keys": ["y"]}
- {"kind": "bar", "title": "...", "data": [...], "x_key": "x", "y_keys": ["y"]}
- {"kind": "text", "heading": "...", "body": "..."}`;

const MODEL = "gemini-3.1-flash-lite-preview"; // Match the working Python script

class App {
  constructor() {
    this.renderer = new Renderer(document.getElementById('dashboard-content'));
    this.currentSpec = null;
    this.keys = { gemini: '', finedge: '' };
    
    this.init();
  }

  async init() {
    // Load keys
    const stored = await chrome.storage.local.get(['gemini_key', 'finedge_key', 'last_spec']);
    this.keys.gemini = stored.gemini_key || '';
    this.keys.finedge = stored.finedge_key || '';
    if (stored.last_spec) {
      this.currentSpec = stored.last_spec;
      this.renderer.render(this.currentSpec);
    }

    // UI Bindings
    document.getElementById('send-btn').onclick = () => this.handlePrompt();
    document.getElementById('user-prompt').onkeypress = (e) => {
      if (e.key === 'Enter') this.handlePrompt();
    };
    document.getElementById('settings-btn').onclick = () => {
      document.getElementById('gemini-key').value = this.keys.gemini;
      document.getElementById('finedge-key').value = this.keys.finedge;
      document.getElementById('settings-panel').classList.toggle('hidden');
    };
    document.getElementById('save-settings').onclick = () => {
      this.keys.gemini = document.getElementById('gemini-key').value;
      this.keys.finedge = document.getElementById('finedge-key').value;
      chrome.storage.local.set({ 
        gemini_key: this.keys.gemini, 
        finedge_key: this.keys.finedge 
      });
      document.getElementById('settings-panel').classList.add('hidden');
    };
  }

  setStatus(msg) {
    document.getElementById('status-bar').textContent = msg;
  }

  async handlePrompt() {
    const input = document.getElementById('user-prompt');
    const prompt = input.value.trim();
    if (!prompt) return;
    if (!this.keys.gemini) {
      alert("Please set your Gemini API key in settings.");
      return;
    }

    input.value = '';
    this.setStatus("Thinking...");
    
    try {
      const spec = await this.plan(prompt);
      this.currentSpec = spec;
      this.renderer.render(spec);
      chrome.storage.local.set({ last_spec: spec });
      this.setStatus("Ready");
    } catch (err) {
      console.error(err);
      this.setStatus("Error: " + err.message);
    }
  }

  async plan(userRequest) {
    let userPrompt = `Current spec: ${JSON.stringify(this.currentSpec)}\nUser request: ${userRequest}`;
    let contents = [{ role: 'user', parts: [{ text: userPrompt }] }];
    
    // Tools definition for Gemini
    const tools = [{
      function_declarations: [
        {
          name: "get_ticker_finance",
          description: "Fetches P&L data for a ticker.",
          parameters: { type: "OBJECT", properties: { ticker: { type: "STRING" } }, required: ["ticker"] }
        },
        {
          name: "get_ticker_ratios",
          description: "Fetches financial ratios for a ticker.",
          parameters: { type: "OBJECT", properties: { ticker: { type: "STRING" } }, required: ["ticker"] }
        }
      ]
    }];

    while (true) {
      const response = await this.callGemini(contents, tools);
      const part = response.candidates[0].content.parts[0];

      if (part.functionCall) {
        const { name, args } = part.functionCall;
        this.setStatus(`Calling ${name}...`);
        const result = await this.executeTool(name, args);
        
        contents.push(response.candidates[0].content);
        contents.push({
          role: 'tool',
          parts: [{ functionResponse: { name, response: { result } } }]
        });
      } else {
        const text = part.text.trim();
        // Extract JSON
        const match = text.match(/\{[\s\S]*\}/);
        return JSON.parse(match ? match[0] : text);
      }
    }
  }

  async callGemini(contents, tools) {
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent?key=${this.keys.gemini}`;
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        system_instruction: { parts: [{ text: SYSTEM_PROMPT }] },
        contents,
        tools
      })
    });
    if (!resp.ok) throw new Error(await resp.text());
    return await resp.json();
  }

  async executeTool(name, args) {
    const ticker = args.ticker || "RELIANCE";
    if (name === 'get_ticker_finance') {
      return await this.fetchFinancials(ticker, 'pl');
    } else if (name === 'get_ticker_ratios') {
      return await this.fetchRatios(ticker);
    }
    return "Unknown tool";
  }

  async fetchFinancials(ticker, type) {
    if (!this.keys.finedge) return "Error: No FinEdge key";
    const url = `https://data.finedgeapi.com/api/v1/financials/${ticker}?statement_type=s&statement_code=${type}&period=annual&token=${this.keys.finedge}`;
    const resp = await fetch(url);
    if (!resp.ok) return `Error: ${await resp.text()}`;
    try {
      return await resp.json();
    } catch (e) {
      return await resp.text();
    }
  }

  async fetchRatios(ticker) {
    if (!this.keys.finedge) return "Error: No FinEdge key";
    const url = `https://data.finedgeapi.com/api/v1/ratios/${ticker}?statement_type=s&ratio_type=pr&token=${this.keys.finedge}`;
    const resp = await fetch(url);
    if (!resp.ok) return `Error: ${await resp.text()}`;
    try {
      return await resp.json();
    } catch (e) {
      return await resp.text();
    }
  }
}

new App();
