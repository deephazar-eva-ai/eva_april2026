# Talk-to-App Dashboard Walkthrough

The **Talk-to-App Dashboard** is a dynamic financial analysis tool that operates directly in your browser. It uses AI to interpret your questions about companies and builds professional dashboards in seconds.

## 📺 Demo Video

![Talk-to-App Extension Demo](file:///home/acer/.gemini/antigravity/brain/f7bf669d-1862-4194-8cd0-ef8e6fa9c165/talk_to_app_demo.mp4)

---

## 🛠️ Getting Started

### 1. Installation
The plugin is currently in developer mode. To install:
1. Open Chrome and go to `chrome://extensions/`.
2. Enable **Developer mode** (top right toggle).
3. Click **Load unpacked** and select the `assignment/chrome_extension` folder.
4. The extension will appear in your extensions list.

### 2. Initial Setup
Before using the dashboard, you need to provide your API keys:
1. Click the extension icon to open the **Side Panel**.
2. Click the **Gear icon (⚙️)** in the header.
3. Enter your **Gemini API Key** and **FinEdge API Key**.
4. Click **Save & Close**.

---

## 💬 How to Use

Simply type a request in the input field at the bottom. The AI will understand your intent and build the UI.

### Examples of Prompts:
*   "Show me a summary of Reliance Industries."
*   "Compare ITC's revenue and profit for the last 5 years."
*   "What are the key financial ratios for HDFC Bank?"
*   "Create a dashboard with a table of Reliance's annual P&L."

---

## ✨ Features & Widgets

The dashboard supports several interactive widgets:

### 1. Stats Cards
Key metrics like Revenue, Net Profit, or PE Ratio are displayed in high-visibility cards.
> [!TIP]
> Stats often include a "sub-label" for context, such as the currency or unit (e.g., "In Cr").

### 2. Interactive Charts
Using `Chart.js`, the extension renders bar and line charts. You can hover over data points to see exact values.
*   **Bar Charts:** Great for comparing yearly revenue or expenses.
*   **Line Charts:** Perfect for tracking trends over time.

### 3. Data Tables
For deep dives, the extension generates formatted tables. 
*   Includes headers and borders for readability.
*   Automatically adjusts to the number of columns returned by the data tools.

### 4. Multi-Tab Layouts
For complex requests, the AI will organize information into **Tabs** (e.g., "P&L Summary", "Key Ratios", "Analysis").

---

## 🔍 Under the Hood

When you send a prompt:
1. **Planning:** `popup.js` sends your prompt to Gemini.
2. **Tool Calling:** Gemini identifies if it needs data (e.g., `get_ticker_finance`).
3. **Execution:** The extension fetches real-time data from **FinEdge API**.
4. **Spec Generation:** Gemini creates a JSON "Spec" defining the widgets.
5. **Rendering:** `renderer.js` clears the current view and paints the new dashboard.
