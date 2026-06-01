from __future__ import annotations

import json
from typing import Optional, Literal

from pydantic import BaseModel, Field


# =========================================================
# Contracts
# =========================================================

GoalStatus = Literal[
    "pending",
    "in_progress",
    "done",
]


import uuid

class Goal(BaseModel):
    """
    Goal identity tracking using UUID.
    """

    goal_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])

    description: str

    done: bool = False

    status: GoalStatus = "pending"

    # Index into memory hits.
    artifact_index: Optional[int] = None
    
    depends_on: list[int] = Field(default_factory=list)


class Observation(BaseModel):
    """
    Perception output.

    Replaces Session-5 Verdict.
    """

    run_id: str

    iteration: int

    goals: list[Goal]

    summary: str

    @property
    def all_done(self) -> bool:
        return all(g.done for g in self.goals)

    def get_ready_goals(self) -> list[Goal]:
        ready = []
        for i, g in enumerate(self.goals):
            if not g.done:
                if all(self.goals[dep].done for dep in g.depends_on if dep < len(self.goals)):
                    ready.append(g)
        return ready


class GoalPlanItem(BaseModel):
    description: str
    depends_on: list[int] = Field(
        default_factory=list,
        description="Indices (0-indexed) of prior goals that must be completed first."
    )

class GoalPlan(BaseModel):
    """
    LLM planner output.
    """

    goals: list[GoalPlanItem]


class MemoryItem(BaseModel):

    memory_id: str

    kind: str

    descriptor: str

    keywords: list[str]

    artifact_id: Optional[
        str
    ] = None

    goal_id: Optional[
        str
    ] = None


# =========================================================
# LLM Gateway
# =========================================================

class LLMGateway:

    def structured(
        self,
        *,
        prompt: str,
        schema: type[BaseModel],
        auto_route: str,
    ):
        raise NotImplementedError


# =========================================================
# Perception
# =========================================================

class Perception:
    """
    Stateful orchestrator.

    Responsibilities
    ----------------

    Iteration 1:
        - query decomposition

    Every iteration:
        - verify goals from history
        - preserve ordering
        - attach artifact indices

    Invariants
    ----------

    - no goal ids
    - positional identity
    - no reordering
    - no insertion
    - no deletion
    - once done always done
    """

    MAX_GOALS = 8

    def __init__(
        self,
        llm: LLMGateway,
    ):

        self.llm = llm

        self.iteration = 0

    # =====================================================
    # Public API
    # =====================================================

    def observe(
        self,
        query: str,
        hits: list[MemoryItem],
        history: list[dict],
        prior_goals: list[Goal],
        run_id: str,
    ) -> Observation:

        self.iteration += 1

        # ------------------------------------------
        # First iteration:
        # Planning
        # ------------------------------------------

        if not prior_goals:

            goals = self._plan(
                query=query,
                hits=hits,
            )

        # ------------------------------------------
        # Later iterations:
        # Verification
        # ------------------------------------------

        else:

            goals = self._verify(
                prior_goals=prior_goals,
                history=history,
                hits=hits,
            )

        return Observation(
            run_id=run_id,
            iteration=self.iteration,
            goals=goals,
            summary=self._summary(
                goals,
                history,
            ),
        )

    # =====================================================
    # Planning
    # =====================================================

    def _plan(
        self,
        query: str,
        hits: list[MemoryItem],
    ) -> list[Goal]:
        """
        One LLM call.

        Produces:
            ordered bounded goals.

        Output has no IDs.
        """

        import datetime
        current_date = datetime.datetime.now().strftime("%A, %B %d, %Y %I:%M %p")

        hits_text = "\n".join(
            f"[{hit.kind}] {hit.descriptor}" for hit in hits
        )

        prompt = f"""
You are Perception.

Decompose the user's query into the most compact, logical, and executable sub-goals possible.
For each goal, provide a 'depends_on' list containing the indices (0-indexed) of any prior goals that must be fully completed before this goal can begin. If a goal can be executed independently or in parallel with others, leave its 'depends_on' list empty.

Rules:
1. Short imperative goals.
2. Combine independent tasks into a SINGLE goal whenever possible to minimize iterations.
3. Preserve execution order, especially for dependent tasks.
4. Maximum {self.MAX_GOALS}.
5. No IDs.
6. No verification.
7. No artifact references.
8. No explanation.
9. Output strictly in JSON format.
10. If the MEMORY HITS indicate that relevant indexed knowledge exists, you MUST emit a generic goal to query the knowledge base before synthesizing an answer. Do NOT emit goals to read the individual source files directly.

CURRENT DATE & TIME:
{current_date}

MEMORY HITS:
{hits_text}

Query:

{query}
"""

        result = (
            self.llm.structured(
                prompt=prompt,
                schema=GoalPlan,
                auto_route="perception",
            )
        )

        return [
            Goal(
                description=g.description,
                depends_on=g.depends_on
            )
            for g in result.goals[
                : self.MAX_GOALS
            ]
        ]

    # =====================================================
    # Replanning
    # =====================================================

    def _plan_update(
        self,
        prior_goals: list[Goal],
        history: list[dict],
    ) -> list[Goal]:
        
        import datetime
        current_date = datetime.datetime.now().strftime("%A, %B %d, %Y %I:%M %p")

        goals_text = "\n".join(
            f"{i}: {g.description}"
            for i, g in enumerate(prior_goals)
        )

        def _format_history(h):
            desc = h.get('result_descriptor', '')
            if "[artifact" in desc and "preview:" in desc:
                # Strip the preview text so Perception doesn't hallucinate goals based on it
                desc = desc.split("preview:")[0].strip() + "]"
            return f"Iter {h.get('iter')} | Action: {h.get('tool')} -> {desc}"

        history_text = "\n".join(
            _format_history(h) for h in history if h.get("kind") == "action"
        )

        prompt = f"""
You are Perception.
Review the ENTIRE current goal plan and the RECENT ACTION HISTORY.

Rules:
1. Preserve all existing goals exactly as they are (especially those marked [done]), EXCEPT when a discovery action has occurred.
2. Append-after-discovery: ONLY if a recent action explicitly discovered a list of concrete items (e.g. files in a directory) that are HIGHLY RELEVANT and MUST be processed individually to fulfill an [open] generic goal, you may append a specific new goal for them. Do NOT blindly append goals for every discovered file.
3. DO NOT treat knowledge retrieval or search tools as discovery actions! The purpose of retrieving chunks is for direct synthesis, NOT to spawn new file-reading goals.
4. NEVER remove or reorder existing goals. If a generic goal is completely replaced by specific appended sub-goals, simply mark the generic goal as [done].
5. NEVER re-append final reporting goals. Instead, use the 'depends_on' field to make them wait for any newly appended goals.
6. Provide a 'depends_on' list containing the indices (0-indexed) of prior goals.

CURRENT GOAL PLAN:
{goals_text}

RECENT ACTION HISTORY:
{history_text}
"""

        result = (
            self.llm.structured(
                prompt=prompt,
                schema=GoalPlan,
                auto_route="perception",
            )
        )

        return [
            Goal(
                description=g.description,
                depends_on=g.depends_on
            )
            for g in result.goals[: self.MAX_GOALS]
        ]

    # =====================================================
    # Verification
    # =====================================================

    def _verify(
        self,
        prior_goals: list[Goal],
        history: list[dict],
        hits: list[MemoryItem],
    ) -> list[Goal]:
        """
        Replaces Verifier.

        Reads history every iteration.
        Optionally uses LLM to dynamically append goals after discovery.
        """

        # 1. Dynamic Replanning (Append-After-Discovery)
        # Only invoke the LLM replanner if there is at least one action in history
        has_actions = any(h.get("kind") == "action" for h in history)
        
        if has_actions:
            new_goals = self._plan_update(prior_goals, history)
            
            # Restore state for preserved goals
            for new_g in new_goals:
                for old_g in prior_goals:
                    if new_g.description == old_g.description:
                        new_g.goal_id = old_g.goal_id
                        new_g.done = old_g.done
                        new_g.status = old_g.status
                        break
            
            working_goals = new_goals
        else:
            working_goals = prior_goals

        updated = []

        for position, goal in enumerate(
            working_goals
        ):

            # ----------------------------------
            # Once done always done
            # ----------------------------------

            if not goal.done:

                if self._goal_done(
                    goal,
                    history,
                ):

                    goal.done = True

                    goal.status = (
                        "done"
                    )

                elif self._goal_started(
                    goal,
                    history,
                ):

                    goal.status = (
                        "in_progress"
                    )

            # ----------------------------------
            # Reset attachment
            # ----------------------------------

            goal.artifact_index = None

            # ----------------------------------
            # Attach to unfinished goals
            # ----------------------------------

            if not goal.done:

                goal.artifact_index = (
                    self._artifact_index(
                        goal,
                        hits,
                    )
                )
                
                if goal.artifact_index is None and hasattr(goal, "depends_on") and goal.depends_on:
                    for dep_idx in goal.depends_on:
                        if dep_idx < len(working_goals):
                            dep_goal_id = working_goals[dep_idx].goal_id
                            dep_art_idx = self._artifact_index_for_dependency(dep_goal_id, hits)
                            if dep_art_idx is not None:
                                goal.artifact_index = dep_art_idx
                                break

            updated.append(goal)

        return updated

    # =====================================================
    # History Evaluation
    # =====================================================

    def _goal_done(
        self,
        goal: Goal,
        history: list[dict],
    ) -> bool:
        """
        Folded verifier logic.
        """
        
        for event in reversed(history):
            if event.get("goal_id") == goal.goal_id:
                if event.get("kind") == "answer":
                    text = event.get("text", "").strip()
                    if not text:
                        continue
                    # If the answer is just a JSON block, it's a hallucinated tool call, not a real answer.
                    if text.startswith("{") and text.endswith("}"):
                        continue
                    if text.startswith("```json") and text.endswith("```"):
                        continue
                    return True

        return False

    def _goal_started(
        self,
        goal: Goal,
        history: list[dict],
    ) -> bool:

        goal_words = set(
            goal.description
            .lower()
            .split()
        )

        for event in history:

            text = json.dumps(
                event
            ).lower()

            overlap = len(
                goal_words
                &
                set(
                    text.split()
                )
            )

            if overlap >= 1:
                return True

        return False

    # =====================================================
    # Artifact Selection
    # =====================================================

    def _artifact_index(
        self,
        goal: Goal,
        hits: list[MemoryItem],
    ) -> Optional[int]:
        """
        Returns index into hits.

        Never returns handle.
        """

        goal_terms = set(
            goal.description
            .lower()
            .split()
        )

        for i, hit in enumerate(
            hits
        ):

            if hasattr(hit, "goal_id") and hit.goal_id == goal.goal_id:
                return i

            overlap = len(
                goal_terms
                &
                {
                    k.lower()
                    for k
                    in hit.keywords
                }
            )

            if overlap > 0:
                return i

        return None

    def _artifact_index_for_dependency(
        self,
        dep_goal_id: str,
        hits: list[MemoryItem],
    ) -> Optional[int]:
        for i, hit in enumerate(hits):
            if not hit.artifact_id:
                continue
            if hasattr(hit, "goal_id") and hit.goal_id == dep_goal_id:
                return i
        return None

    # =====================================================
    # Helpers
    # =====================================================

    def _first_open_goal(
        self,
        goals: list[Goal],
    ) -> Optional[int]:

        for i, g in enumerate(
            goals
        ):
            if not g.done:
                return i

        return None

    def _summary(
        self,
        goals: list[Goal],
        history: list[dict],
    ) -> str:

        completed = sum(
            g.done
            for g in goals
        )

        return (
            f"{completed}/"
            f"{len(goals)} goals "
            f"completed after "
            f"{len(history)} events"
        )