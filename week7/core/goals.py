# pyrefly: ignore [missing-import]
from .schemas import Goal


class GoalManager:
    def build_goals(self, query: str):
        return [
            Goal(
                id="goal-1",
                description=query,
            )
        ]

    def all_done(self, goals):
        return all(goal.done for goal in goals)