import json
from pathlib import Path
# pyrefly: ignore [missing-import]
from schemas import ActionRecord


class HistoryManager:
    def __init__(self, path="storage/history.json"):
        self.path = Path(path)

        self.path.parent.mkdir(parents=True, exist_ok=True)

        if not self.path.exists():
            self.path.write_text("[]")

    def append(self, record: ActionRecord):
        history = self.load()
        history.append(record.model_dump())

        self.path.write_text(
            json.dumps(history, indent=2)
        )

    def load(self):
        return json.loads(self.path.read_text())