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


class Goal(BaseModel):
    """
    Positional identity.

    No goal_id.
    Position in list is identity.
    """

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
                query=query
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
    ) -> list[Goal]:
        """
        One LLM call.

        Produces:
            ordered bounded goals.

        Output has no IDs.
        """

        import datetime
        current_date = datetime.datetime.now().strftime("%A, %B %d, %Y %I:%M %p")

        prompt = f"""
You are Perception.

Decompose the user's query into the most compact, logical, and executable sub-goals possible.
For each goal, provide a 'depends_on' list containing the indices (0-indexed) of any prior goals that must be fully completed before this goal can begin. If a goal can be executed independently or in parallel with others, leave its 'depends_on' list empty.

Rules:
1. Short imperative goals.
2. Combine independent information-gathering tasks into a SINGLE goal whenever possible to minimize iterations.
3. Preserve execution order, especially for dependent tasks.
4. Do not create separate goals for gathering context (like 'determine the current date', 'find location', or 'search the web'). The execution layer will handle this implicitly.
5. Maximum {self.MAX_GOALS}.
6. No IDs.
7. No verification.
8. No artifact references.
9. No explanation.
10. Output strictly in JSON format.

CURRENT DATE & TIME:
{current_date}

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

        Updates only:
            done
            status
            artifact_index
        """

        updated = []

        for position, goal in enumerate(
            prior_goals
        ):

            # ----------------------------------
            # Once done always done
            # ----------------------------------

            if not goal.done:

                if self._goal_done(
                    goal,
                    history,
                    position,
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
                        position,
                    )
                )
                
                if goal.artifact_index is None and hasattr(goal, "depends_on") and goal.depends_on:
                    for dep_idx in goal.depends_on:
                        dep_art_idx = self._artifact_index_for_dependency(dep_idx, hits)
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
        position: int = -1,
    ) -> bool:
        """
        Folded verifier logic.
        """
        
        for event in reversed(history):
            if event.get("kind") == "answer" and event.get("goal_position") == position:
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
        goal_position: int,
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

            if not hit.artifact_id:
                continue
                
            if hasattr(hit, "goal_id") and hit.goal_id == str(goal_position):
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
        dep_idx: int,
        hits: list[MemoryItem],
    ) -> Optional[int]:
        for i, hit in enumerate(hits):
            if not hit.artifact_id:
                continue
            if hasattr(hit, "goal_id") and hit.goal_id == str(dep_idx):
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