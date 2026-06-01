from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class Goal(BaseModel):
    id: str
    description: str
    done: bool = False


class ActionRecord(BaseModel):
    step: int
    tool: str
    tool_input: Dict[str, Any]
    output_summary: str
    artifact_id: Optional[str] = None


class Artifact(BaseModel):
    artifact_id: str
    tool_name: str
    content: str


class PerceptionResult(BaseModel):
    visible_context: str
    attached_artifacts: List[str] = []
    updated_goals: List[Goal] = []


class DecisionResult(BaseModel):
    final_answer: Optional[str] = None
    tool_call: Optional[Dict[str, Any]] = None


class ToolResult(BaseModel):
    summary: str
    artifact_content: Optional[str] = None


class MemoryItem(BaseModel):
    key: str
    value: str
    category: str
    tags: List[str] = []
    score: float = 1.0


class Observation(BaseModel):
    visible_context: str
    memory_items: List[MemoryItem]
    attached_artifacts: List[str]
    updated_goals: List[Goal]


class DecisionOutput(BaseModel):
    final_answer: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None