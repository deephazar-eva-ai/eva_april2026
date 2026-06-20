# 13. Running safely on your real machine (enterprise)

`cua-driver` runs on the real host. The agent controls your actual apps, sees your files, can read clipboard contents, can navigate to authenticated sites in your browser. An agent bug that closes the wrong file or sends the wrong email has real consequences.

The full sandbox path is the cua Python SDK with `Sandbox.ephemeral(Image.macos())`, which boots a macOS VM through Apple's Virtualization framework. Heavyweight (gigabytes of disk, slow startup), macOS-only. In Session 12 we will cover proper container isolation.

For any enterprise effort on **Linux**, the recommended setup:

1. **A fresh user account** on the machine for any run. Grant permissions to `cua-driver` under that account. The agent operates only on test files inside that account's home directory.
   *(You can use the provided `setup_linux_enterprise_sandbox.sh` script to automatically create this user and configure the workspace.)*
2. **A backup** of any data the agent might touch. The setup script creates a tarball snapshot of your test data prior to runs.
3. **The verify step** on every action, especially destructive ones. The agent is explicitly instructed to re-read the window state after any file deletion, app closure, or data mutation to ensure it executed the correct action.
4. **`kill_app` and `Ctrl+Z` (Undo)** are the two recovery primitives. Test them before recording. If an action goes wrong, use `Ctrl+Z` (via `desktop_judgment` hotkey) to revert the edit, or forcefully close the app with `kill_app`.

If a run goes out of control, `cua-driver shutdown` kills the daemon and the agent stops within a second.
