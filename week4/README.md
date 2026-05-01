Listed directory week4
Listed directory UI
Listed directory prefab
Listed directory 04_talk_to_app
Listed directory assignment
Listed directory chrome_extension
Viewed manifest.json:1-24
Viewed popup.html:1-50
Viewed popup.js:1-182
Viewed renderer.js:1-137

The **Talk-to-App Dashboard** is a dynamic Chrome extension designed to turn natural language prompts into interactive financial dashboards. It serves as a browser-based port of the Python "Talk-to-App" project, leveraging AI to fetch data and design UI layouts on the fly.

### 🚀 Core Functionality
*   **Natural Language Interaction:** Users can describe the dashboard they want (e.g., *"Show me ITC financials and key ratios for the last 3 years"*).
*   **AI Planning:** The extension uses **Gemini 1.5 Flash** (via `popup.js`) to process user requests, decide which financial tools to call, and generate a JSON "dashboard spec."
*   **Dynamic Rendering:** A custom `Renderer` class (in `renderer.js`) takes the AI-generated spec and builds a UI consisting of tabs, stats, tables, and charts.

### 🛠️ Key Technical Components
*   **Tool Integration:**
    *   `get_ticker_finance`: Fetches P&L data (Revenue, Net Profit, etc.) from the **FinEdge API**.
    *   `get_ticker_ratios`: Fetches key metrics like PE Ratio, ROE, and Debt-to-Equity.
*   **Visualizations:** Uses **Chart.js** to render responsive line and bar charts.
*   **Side Panel UI:** Implemented as a Chrome **Side Panel** (Manifest V3), allowing it to stay open while you browse different financial news sites or stock pages.
*   **Storage:** Securely stores your Gemini and FinEdge API keys locally using `chrome.storage.local`.

### 📂 Project Structure
*   `manifest.json`: Defines extension metadata and permissions (Side Panel, Storage, Host permissions).
*   `popup.html`: The main container for the dashboard and settings panel.
*   `popup.js`: The "brain" that communicates with Gemini and coordinates tool calls.
*   `renderer.js`: The engine that transforms JSON specs into HTML/Canvas elements.
*   `style.css`: Provides a modern, dark-themed aesthetic with "glassmorphism" card designs.

### 💡 Example Workflow
1.  **User Prompt:** "Compare RELIANCE revenue vs profit."
2.  **AI Action:** Gemini calls `get_ticker_finance(ticker="RELIANCE")`.
3.  **Data Processing:** The AI receives the raw JSON data, extracts the relevant years, and formats it into a `bar` or `line` chart spec.
4.  **UI Update:** The side panel instantly refreshes with a professional-looking dashboard containing the requested comparison.