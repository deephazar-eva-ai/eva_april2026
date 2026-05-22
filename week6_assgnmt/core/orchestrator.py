from __future__ import annotations

import asyncio
import json
import uuid

from core.memory import MemoryService as Memory
from core.perception import Perception
from core.decision import Decision
from core.action import Action
from core.artifacts import ArtifactStore
from core.schemas import Goal


MAX_ITERATIONS = 24


class Agent6Orchestrator:
    """
    Final S6 orchestrator.

    Loop:

        remember(query)
            ↓
        memory.read()
            ↓
        perception.observe()
            ↓
        decision.next_step()
            ↓
        action.execute()
            ↓
        memory.record_outcome()
            ↓
        history
            ↓
        repeat

    Stop:
        observation.all_done
    """

    def __init__(
        self,
        *,
        memory: Memory,
        perception: Perception,
        decision: Decision,
        action: Action,
        artifacts: ArtifactStore,
        gateway,
        mcp_session,
        load_tools,
        mcp_tools_for_decision,
    ):

        self.memory = memory

        self.perception = perception

        self.decision = decision

        self.action = action

        self.artifacts = artifacts

        self.gateway = gateway

        self.mcp_session = (
            mcp_session
        )

        self.load_tools = (
            load_tools
        )

        self.mcp_tools_for_decision = (
            mcp_tools_for_decision
        )

    # =====================================================
    # Run
    # =====================================================

    async def run(
        self,
        query: str,
    ) -> str:

        run_id = (
            uuid.uuid4()
            .hex[:8]
        )

        history: list[
            dict
        ] = []

        prior_goals: list[
            Goal
        ] = []

        # --------------------------------------
        # Durable memory
        # --------------------------------------

        self.memory.remember(
            query,
            source=(
                "user_query"
            ),
            run_id=run_id,
        )

        async with (
            self.mcp_session()
            as session
        ):

            mcp_tools = (
                await self.load_tools(
                    session
                )
            )

            tools = (
                self
                .mcp_tools_for_decision(
                    mcp_tools
                )
            )

            # ----------------------------------
            # Main loop
            # ----------------------------------

            for it in range(
                1,
                MAX_ITERATIONS
                + 1,
            ):
                print(f"\n─── iter {it} ───")

                # ------------------------------
                # Memory
                # ------------------------------

                hits = (
                    self.memory.read(
                        query=query,
                        history=history,
                        current_run_id=run_id,
                    )
                )
                print(f"[memory.read]   {len(hits)} hits")

                # ------------------------------
                # Perception
                # ------------------------------

                obs = (
                    self.perception.observe(
                        query=query,
                        hits=hits,
                        history=history,
                        prior_goals=(
                            prior_goals
                        ),
                        run_id=run_id,
                    )
                )

                print("[perception]    ", end="")
                for i, g in enumerate(obs.goals):
                    status_str = "[done]" if g.done else "[open]"
                    prefix = "" if i == 0 else "                "
                    print(f"{prefix}{status_str} {g.description}")
                    if not g.done and g.artifact_index is not None:
                        hit = hits[g.artifact_index]
                        if hit.artifact_id:
                            print(f"                  attach=art:{hit.artifact_id}")

                prior_goals = (
                    obs.goals
                )

                # ------------------------------
                # Completion
                # ------------------------------

                if (
                    obs.all_done
                ):
                    print(f"\n[done] all {len(obs.goals)} goals satisfied")
                    break

                ready_goals = obs.get_ready_goals()
                if not ready_goals:
                    print("\n[error] Deadlock detected: no goals ready but not all done.")
                    break

                all_out_tool_calls = []
                
                for goal in ready_goals:
                    # ------------------------------
                    # Artifact attach
                    # ------------------------------
    
                    attached = []
    
                    if (
                        goal
                        .artifact_index
                        is not None
                    ):
    
                        hit = hits[
                            goal
                            .artifact_index
                        ]
    
                        if (
                            hit.artifact_id
                            and
                            self
                            .artifacts
                            .exists(
                                hit.artifact_id
                            )
                        ):
                            bytes_len = len(self.artifacts.get_bytes(hit.artifact_id))
                            print(f"[attach]        art:{hit.artifact_id} ({bytes_len} bytes)")
    
                            attached.append(
                                (
                                    hit.artifact_id,
                                    self
                                    .artifacts
                                    .get_bytes(
                                        hit
                                        .artifact_id
                                    ),
                                )
                            )
    
                    # ------------------------------
                    # Decision
                    # ------------------------------
    
                    goal_position = prior_goals.index(goal)
                    goal_tool_calls = sum(
                        1 for event in history
                        if event.get("kind") == "action" and event.get("goal_position") == goal_position
                    )
                    
                    goal_tools = tools if goal_tool_calls == 0 else []

                    try:
                        out = (
                            self.decision
                            .next_step(
                                goal=goal,
                                hits=hits,
                                attached=attached,
                                history=history,
                                mcp_tools=goal_tools,
                            )
                        )
                    except ValueError as e:
                        error_msg = f"Error in decision: {e}"
                        print(f"[decision]      ERROR: {error_msg}")
                        
                        self.memory.record_outcome(
                            tool_call="system",
                            result_text=error_msg,
                            artifact_id=None,
                            run_id=run_id,
                            goal_id=str(prior_goals.index(goal)),
                        )
                        
                        history.append(
                            {
                                "iter": it,
                                "kind": "action",
                                "goal_position": prior_goals.index(goal),
                                "tool": "system",
                                "arguments": {},
                                "result_descriptor": error_msg,
                                "artifact_id": None,
                            }
                        )
                        continue
    
                    if out.tool_calls:
                        for tc in out.tool_calls:
                            args_str = json.dumps(tc.arguments)
                            print(f"[decision]      TOOL_CALL: {tc.name}({args_str})")
                            all_out_tool_calls.append((goal, tc))
                    elif out.answer:
                        preview = out.answer.replace("\\n", " ")
                        if len(preview) > 60:
                            preview = preview[:60] + "..."
                        print(f"[decision]      ANSWER: {preview}")
    
                    # ------------------------------
                    # Answer
                    # ------------------------------
    
                    if (
                        out.answer
                        is not None
                    ):
    
                        history.append(
                            {
                                "iter":
                                it,
    
                                "kind":
                                "answer",
    
                                "goal_position":
                                (
                                    prior_goals
                                    .index(
                                        goal
                                    )
                                ),
    
                                "text":
                                out.answer,
                            }
                        )
    
                # ------------------------------
                # Action
                # ------------------------------
                
                if not all_out_tool_calls:
                    continue

                tasks = [
                    self.action.execute(session, tc)
                    for _, tc in all_out_tool_calls
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for (goal, tc), result in zip(all_out_tool_calls, results):
                    if isinstance(result, Exception):
                        result_text = f"Error executing tool {tc.name}: {result}"
                        art_id = None
                    else:
                        result_text, art_id = result
                    
                    bytes_len = len(self.artifacts.get_bytes(art_id)) if art_id else 0
                    preview = result_text.replace("\\n", " ")
                    if len(preview) > 40:
                        preview = preview[:40] + "..."
                    print(f"[action]        → [artifact art:{art_id}, {bytes_len} bytes] preview: {preview}")

                    # ------------------------------
                    # Memory write
                    # ------------------------------

                    self.memory.record_outcome(
                        tool_call=tc,
                        result_text=result_text,
                        artifact_id=art_id,
                        run_id=run_id,
                        goal_id=str(prior_goals.index(goal)),
                    )

                    # ------------------------------
                    # History
                    # ------------------------------

                    history.append(
                        {
                            "iter": it,
                            "kind": "action",
                            "goal_position": prior_goals.index(goal),
                            "tool": tc.name,
                            "arguments": tc.arguments,
                            "result_descriptor": result_text[:300],
                            "artifact_id": art_id,
                        }
                    )

        return self._final_answer(
            query,
            history
        )

    # =====================================================
    # Final Answer
    # =====================================================

    def _final_answer(
        self,
        query: str,
        history: list[
            dict
        ],
    ) -> str:

        answers = [
            h["text"]
            for h in history
            if h["kind"]
            == "answer"
        ]

        if not answers:
            return "Completed."

        combined = "\n\n".join(answers)

        prompt = f"""
You are the Orchestrator's final synthesis component.

User Query:
{query}

Intermediate Findings:
{combined}

Task:
Produce a single, coherent final answer that directly addresses the user's query using ONLY the intermediate findings provided above.
Remove any repetitive or redundant information. Do NOT start your response with "FINAL ANSWER:" or similar prefixes.
"""

        response = self.gateway.invoke(
            prompt=prompt,
            tools=None,
            tool_choice=None,
            auto_route="decision",
        )

        text = response.text or ""
        text = text.strip()
        if text.startswith("FINAL ANSWER:"):
            text = text[13:].strip()
        elif text.startswith("FINAL:"):
            text = text[6:].strip()
        
        return "FINAL: " + text