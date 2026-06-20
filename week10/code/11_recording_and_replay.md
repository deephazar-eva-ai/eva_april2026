# 11. Recording and Replay

`cua-driver` ships with `start_recording` and `replay_trajectory`. Use them to ensure that every agent run is properly recorded and can be replayed later.

Every run records to a turn-numbered directory of `(tool, args)` pairs. 
- When the agent fails, the trajectory is the **evidence**. 
- When it succeeds, the trajectory is a **regression test**.

## 1. Recording a Trajectory

Wrap your agent execution in a `try...finally` block. Start the recording before the agent begins, and ensure it stops when the agent finishes (even on failure).

```python
# Start the recording, saving to a session-specific directory
call("start_recording", {"output_dir": f"/tmp/run-{session_id}"})

try:
    run_agent(goal)
finally:
    # Always ensure the recording is stopped
    call("stop_recording", {})
```

## 2. Replaying a Trajectory

To verify or debug a run, you can replay the exact sequence of UI interactions against the **same starting UI state**.

```python
# Replay the trajectory from the saved directory
call("replay_trajectory", {"trajectory_dir": f"/tmp/run-{session_id}"})
```
