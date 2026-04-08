# Authentic Website Detector: Walkthrough

## Summary of Changes
I have built the Authentic Website Detector Chrome Extension from the ground up, utilizing local, fast heuristics to score and evaluate the authenticity of current websites.

### Completed Components:
1. **Manifest Configuration**: Wrote `manifest.json` for Manifest V3 with `activeTab` permissions.
2. **Branding**: Generated a sleek, neon blue shield icon which has been mapped to sizes 16px, 48px, and 128px for the extension tray.
3. **User Interface**: Designed `popup.html` and `popup.css` focusing on premium aesthetics using glassmorphism, a dark layout, a circular loading animation, and a dynamic scoring indicator.
4. **Heuristic Engine**: Implemented `detector.js` which scores paths out of 100 based on:
   - HTTPS presence
   - Extraneous subdomains
   - Suspicious phishing keywords (e.g., 'login', 'secure', 'account') coupled with dashes.
   - Usage of Homoglyphs/Punycode.
   - Spam-associated Top-Level Domains.
5. **UI Integration**: Established `popup.js` to animate the score dial natively upon receiving the URL from the active tab.

## Code Snapshots
Here is the core logical scoring implementation:
```javascript
// From detector.js
if (domainParts.length > 3 && !url.hostname.includes('github.io')) {
    this.addRationale('neg', 'Unusually high number of subdomains.', -30);
}
// Homoglyph attack check
if (url.hostname.includes('xn--')) {
    this.addRationale('neg', 'Domain uses Punycode (often used for mimicking safe URLs).', -80);
}
```

## How to Test and Verify

Please load the extension into your Chrome browser mechanically:
1. Navigate to `chrome://extensions` in your Google Chrome browser.
2. Enable "Developer mode" by toggling the switch in the top right corner.
3. Click "Load unpacked" on the top left.
4. Select the `/home/admins/eva_april2026/week1_assgnmt/cleanwebsite` folder.
5. Pin the extension to your toolbar, browse different URLs, and click the neon blue shield icon to view the scoring pop-up.

> [!TIP]
> **Try these tests:**
> - `https://google.com` - should show an ~100% score (Authentic)
> - `http://login-verify-account.web.app` or similar local test hosts - should show a degraded score (Suspicious / Unsafe)

Let me know if you would like me to adjust the scoring balance or change any of the colors for the popup!
