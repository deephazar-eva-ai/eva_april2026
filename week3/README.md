# Stock Spike Analyzer Agent (Chrome Extension)

Designed as a Manifest V3 Side Panel extension, this plugin brings a fully autonomous AI financial analyst directly into your browser.

## What It Does:

1. **Agentic Reasoning Loop**
   You input stock tickers (e.g., `ADANIPOWER.NS`) and a date range. Powered by the Gemini API, the plugin initiates an autonomous "thought loop," deciding exactly which tools to execute and in what order to comprehensively answer your query.

2. **Data Acquisition & Math**
   It natively hits Yahoo Finance (via a CORS proxy) to retrieve daily stock prices. Then, it calculates daily mathematical percentage returns to identify significant pricing "spikes" over your given threshold.

3. **News & Sentiment Correlation**
   For every unique date where a stock spiked, the agent queries the current web for related news via the NewsAPI. It parses the headlines, runs them through a JavaScript-based text sentiment analyzer (categorizing them as positive, negative, or neutral), and constructs a summary explaining the likely market cause for each spike.

4. **Rich Visual Output**
   Rather than printing a simple block of text, the agent reveals its live reasoning process incrementally as it thinks. Once the analysis concludes, the final insights are presented in a clean, color-coded, tabular format right in your browser's side panel—letting you review the correlated news and financial shifts at a single glance.

   youtube recording link - https://youtu.be/e5rwvxhw5Ys
