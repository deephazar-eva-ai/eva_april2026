# Key Mapping Bug Fix (xdotool type_text vs hotkey)

### The Problem
During the agent's attempt to use the LibreOffice Standard Filter and Sort dialogs, it mistakenly combined keystrokes (like `tab` and `enter`) with literal text injection using `desktop_judgment`'s `type_text` action. 

For example, the agent submitted:
`{'action_type': 'type_text', 'action_value': 'Status\t=\tPending\tAND\tDue Date\t<\t2026-06-19\tenter'}`

Because the backend relies on `xdotool type` for `type_text`, it literally typed every character in the string! Instead of pressing the Tab key, it typed the backslash and the letter "t" (or just blank spaces). Later, when renaming the sheet, it used `type_text` for `"Overdue enter"`, meaning it literally named the sheet `"Overdue enter"` instead of typing the name and pressing the Enter key to confirm.

### The Fix
To permanently prevent this, Trap 9 in the agent's system prompt (`code/prompts/computer.md`) was updated to explicitly forbid mixing keystrokes and text strings.

The agent is now strictly instructed:
1. **Separate Actions:** It MUST use separate tool calls to differentiate typing text from pressing keys.
2. **Keystroke Enforcement:** It MUST use `action_type: hotkey` for `tab`, `enter`, `down`, etc.
3. **Literal Typing Warning:** It CANNOT put "tab" or "enter" into a `type_text` string, as the system will literally type the word instead of pressing the key.

The prompt now provides the exact alternating sequence needed to navigate dialogs (e.g., `type_text` "Status" -> `hotkey` "tab" -> `type_text` "=" -> `hotkey` "tab").

---

### Additional Bug: Obsolete Menu Shortcuts & Data Corruption

During subsequent testing, a second related bug emerged regarding sheet operations:

**The Problem:**
1. **Insert Sheet Failure:** The agent attempted to use `shift+f11` to insert a new sheet. While this works in Excel, it does nothing by default in LibreOffice Calc.
2. **Rename Failure & Corruption:** Because the new sheet was never created, the agent attempted to rename the *existing* sheet using `alt+o s r` (Format -> Sheet -> Rename). However, LibreOffice 7.x moved the Sheet operations to a dedicated `Alt+S` menu, rendering the old shortcut useless.
3. **Data Overwrite:** Since no dialogs opened, the agent's subsequent `type_text` action literally typed "sr" (from the failed shortcut) followed by "Overdue" directly into cell A1, overwriting the "Task ID" header with `srOverdue` and corrupting the spreadsheet data!

**The Fix:**
- The agent's instructions in `computer.md` (Trap 9) were updated to use the explicit, modern LibreOffice 7.x menu accelerators:
  - **Insert Sheet:** `alt+s i enter`
  - **Rename Sheet:** `alt+s r`
- The corrupted `tasklist.ods` file was manually restored from its `tasklist.ods.bak` backup to ensure a clean testing environment.
