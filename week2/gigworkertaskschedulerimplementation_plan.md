# Convert Gig Track Pro to Chrome Extension

This plan outlines the steps to transform the existing Gig Track Pro web app into a robust Chrome Extension.

## Proposed Changes

### Global Refactoring for Extension Compatibility

#### [MODIFY] [manifest.json](file:///home/admins/eva_april2026/week2_assgnmt_gemini_flash_lite/gig_worker_task_scheduler/manifest.json)
- Solidify Manifest V3 configuration.
- Add necessary permissions: `storage` and `host_permissions` for Geocoding APIs.

#### [MODIFY] [index.html](file:///home/admins/eva_april2026/week2_assgnmt_gemini_flash_lite/gig_worker_task_scheduler/index.html)
- Localize Font Awesome and Google Fonts.
- Adjust layout for popup dimensions (e.g., `min-width: 500px`).
- Remove any remaining external script dependencies.

#### [MODIFY] [app.js](file:///home/admins/eva_april2026/week2_assgnmt_gemini_flash_lite/gig_worker_task_scheduler/app.js)
- Implement `chrome.storage.local` to persist tasks and origin between popup sessions.
- Ensure all API fetches (Nominatim) are handled correctly within the extension context.
- Load saved data on `DOMContentLoaded`.

#### [NEW] [vendor/](file:///home/admins/eva_april2026/week2_assgnmt_gemini_flash_lite/gig_worker_task_scheduler/vendor/)
- Download and store Font Awesome 6.4.0 assets.
- Download and store Outfit font files.

## User Review Required

> [!IMPORTANT]
> **Persistence**: The web app currently loses all data on refresh. For the extension, I will implement `chrome.storage.local` so your tasks are saved even after closing the popup.
> 
> **Map Connectivity**: The extension requires an internet connection to load OpenStreetMap tiles and perform geocoding.

## Open Questions

- Do you have a preferred width for the extension popup? (Defaulting to ~500px for a good balance).
- Are there any specific icons or logos you'd like to use for the extension icon itself?

## Verification Plan

### Manual Verification
- Load the directory as an unpacked extension in Chrome.
- Verify that the map loads correctly.
- Add a task and verify it persists after closing and reopening the popup.
- Test the "Generate Plan" feature to ensure the optimization algorithm works in the extension context.
- Check that all icons (Font Awesome) and fonts (Outfit) render correctly from local sources.
