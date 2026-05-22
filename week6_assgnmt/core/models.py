import time
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class Goal(BaseModel):

    description: str

    done: bool = False

    status: str = "pending"

    artifact_index: int | None = None

    depends_on: list[int] = []

class ToolCall(BaseModel):
    """
    Single MCP dispatch.
    """

    name: str

    arguments: dict[str, Any]

class ActionRecord(BaseModel):
    step: int
    tool: str
    tool_input: Dict[str, Any]
    output_summary: str
    artifact_id: Optional[str] = None


class Artifact(BaseModel):
    """
    Artifact metadata only.

    Raw bytes live separately on disk.
    """

    artifact_id: str

    sha256: str

    size_bytes: int

    content_type: str

    source: str

    descriptor: str

    created_at: float = Field(
        default_factory=time.time
    )



class PerceptionResult(BaseModel):
    visible_context: str
    attached_artifacts: List[str] = []
    updated_goals: List[Goal] = []


class DecisionOutput(BaseModel):
    """
    Exactly one field populated.

    answer XOR tool_call
    """

    answer: Optional[
        str
    ] = None

    tool_calls: list[
        ToolCall
    ] = []


class ToolResult(BaseModel):
    summary: str
    artifact_content: Optional[str] = None

from typing import Literal


MemoryKind = Literal[
    "fact",
    "preference",
    "tool_outcome",
    "scratchpad",
]


class MemoryItem(BaseModel):
    """
    Canonical typed memory object.
    """

    memory_id: str

    kind: MemoryKind

    source: str

    run_id: Optional[str] = None
    goal_id: Optional[str] = None

    raw_text: str

    descriptor: str

    keywords: list[str] = []

    structured_value: dict[str, Any] = {}

    tags: list[str] = []

    created_at: float = Field(
        default_factory=time.time
    )

    score: float = 1.0

    @property
    def artifact_id(self) -> Optional[str]:
        return self.structured_value.get("artifact_id")


# =========================================================
# Gateway Contracts
# =========================================================

class GatewayToolCall(BaseModel):

    name: str

    arguments: dict[str, Any]


class RouterDecision(BaseModel):

    tier: str

    reason: str | None = None


class GatewayResponse(BaseModel):
    """
    Session-5 gateway response.
    """

    text: str | None = None

    tool_calls: list[
        GatewayToolCall
    ] = []

    router_decision: (
        RouterDecision
        | None
    ) = None

class Gateway:

    def invoke(
        self,
        *,
        prompt: str,
        tools: list[dict],
        tool_choice: str,
        auto_route: str,
    ) -> GatewayResponse:
        raise NotImplementedError
        

class ContentBlock(BaseModel):
    """
    MCP content block.
    """

    text: str


class MCPResult(BaseModel):
    """
    MCP normalized response.
    """

    content: list[ContentBlock]

    content_type: str = (
        "text/plain"
    )


class ClientSession:

    async def call_tool(
        self,
        name: str,
        arguments: dict,
    ) -> MCPResult:
        raise NotImplementedError
