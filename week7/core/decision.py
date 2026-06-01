# =========================================================
# Decision
# =========================================================

from core.models import (
    Goal,
    MemoryItem,
    DecisionOutput,
    GatewayResponse,
    RouterDecision,
    ToolCall,
    Gateway,
)

class Decision:
    """
    One LLM call.

    Inputs:
        goal
        memory hits
        attached artifacts
        history
        MCP tools

    Output:
        answer
        OR
        tool_call
    """

    MAX_HISTORY = 12
    MAX_MEMORY = 8
    MAX_ARTIFACT_BYTES = 64_000

    def __init__(
        self,
        gateway: Gateway,
    ):

        self.gateway = gateway

    # =====================================================
    # Public API
    # =====================================================

    def next_step(
        self,
        goal: Goal,
        hits: list[MemoryItem],
        attached: list[
            tuple[str, bytes]
        ],
        history: list[dict],
        mcp_tools: list[dict],
    ) -> DecisionOutput:
        """
        One gateway call.

        tools=mcp_tools
        tool_choice="auto"
        auto_route="decision"
        """

        prompt = self._build_prompt(
            goal=goal,
            hits=hits,
            attached=attached,
            history=history,
        )

        response = (
            self.gateway.invoke(
                prompt=prompt,
                tools=mcp_tools,
                tool_choice="auto",
                auto_route="decision",
            )
        )

        self._observe_router(
            response.router_decision
        )

        return self._parse(
            response
        )

    # =====================================================
    # Prompt
    # =====================================================

    def _build_prompt(
        self,
        *,
        goal: Goal,
        hits: list[MemoryItem],
        attached: list[
            tuple[str, bytes]
        ],
        history: list[dict],
    ) -> str:
        import datetime
        current_date = datetime.datetime.now().strftime("%A, %B %d, %Y %I:%M %p")

        import re

        memory_text = "\n".join(
            (
                f"- {m.kind}: "
                f"{m.descriptor}"
            )
            for m in hits[
                : self.MAX_MEMORY
            ]
        )
        memory_block = re.sub(r"art:[a-zA-Z0-9]+", "[Attached Artifact]", memory_text)

        history_text = "\n".join(
            str(h)
            for h in history[
                -self.MAX_HISTORY :
            ]
        )
        history_block = re.sub(r"art:[a-zA-Z0-9]+", "[Attached Artifact]", history_text)

        artifacts = []

        for name, blob in attached:

            blob = blob[
                : self.MAX_ARTIFACT_BYTES
            ]

            try:

                content = (
                    blob.decode(
                        "utf-8",
                        errors="replace",
                    )
                )

            except Exception:

                content = (
                    "<binary>"
                )

            artifacts.append(
                (
                    f"[Attached Content]\n"
                    f"{content}"
                )
            )

        artifact_block = (
            "\n\n".join(
                artifacts
            )
        )

        return f"""
You are Decision.

Your job is to choose
the next action.


OUTPUT RULE

You have access to tools. If you need to search for information, fetch content, or perform an action, call the appropriate tool USING THE NATIVE TOOL CALLING API.
If you already have enough information to fulfill the current goal based on MEMORY HITS or RECENT HISTORY, provide a substantive FINAL ANSWER in plain text.

CRITICAL: Do NOT output JSON blocks like `{{"actions": [...]}}` or `{{"goal": ...}}` in your text response. To call a tool, you MUST use the actual tool calling function mechanism, not plain text JSON.

Never produce both a tool call and a final answer in the same response.


ARTIFACT RULE

Strings beginning with:

art:

are internal artifact handles.

Artifact handles are NOT:

- URLs
- file paths
- tool arguments

Never pass art:
to tools.

If artifact content
is needed:

read ATTACHED ARTIFACTS.


SUBSTANTIVE ANSWER RULE

For:

- extraction
- summarization
- comparison
- selection
- recommendation
- listing
- analysis

produce the actual result.

Do not respond with:

"I fetched it"

"How would you like
to continue?"

Provide:

- at least 3 sentences

OR

- a list of results


GENERAL RULES

- call multiple tools in parallel if needed
- prioritize decisive action: once you identify a relevant target (URL, file, etc.), use the appropriate tool to process it immediately. If a file path is provided in the goal for indexing, call the appropriate indexing tool directly; do NOT verify its existence first.
- For information synthesis or knowledge-based queries, rely EXCLUSIVELY on your knowledge retrieval tools as your primary source of truth. Do NOT manually crawl the file system using directory listing or file reading tools unless the goal explicitly asks you to inspect specific files.
- IF a retrieval tool returns chunks, synthesize your final ANSWER immediately from those chunks. You are FORBIDDEN from reading the full source files of those chunks. If the chunks lack details, answer with the best available information from them.
- If an action completes successfully and requires no information extraction or synthesis (e.g., a file was indexed, written, or modified), simply output ANSWER: Action completed successfully.
- CRITICAL: MINIMIZE ITERATIONS. You must NOT perform more than 2 searches for the same goal. If you cannot find exact information, gracefully degrade to the best available approximation or proxy data and output a final ANSWER immediately. Do NOT get stuck in a search loop.
- absolutely NO narration ("I will now search...", "Let me fetch...")
- absolutely NO conversational filler ("Here are the results:", "Based on the memory...")
- absolutely NO planning or verification
- if you are calling a tool, DO NOT output any text or answer alongside it.
- operate only on
  current goal

CURRENT DATE & TIME
{current_date}

CURRENT GOAL

{goal.description}


MEMORY HITS

{memory_block}


RECENT HISTORY

{history_block}


ATTACHED ARTIFACTS

{artifact_block}
"""

    # =====================================================
    # Response Parsing
    # =====================================================

    def _parse(
        self,
        response: GatewayResponse,
    ) -> DecisionOutput:
        """
        Extract all tool calls or answer.
        """

        if response.tool_calls:
            calls = []
            for tc in response.tool_calls:
                self._reject_artifacts(tc.arguments)
                calls.append(
                    ToolCall(
                        name=tc.name,
                        arguments=tc.arguments,
                    )
                )
            
            return DecisionOutput(
                tool_calls=calls
            )

        text = response.text or ""
        
        # Check for hallucinated JSON tool calls
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            import json
            try:
                json.loads(stripped)
                raise ValueError(
                    "You attempted to output a JSON block instead of using native tool calling. "
                    "You MUST use the native tool calling feature of the API to call tools. "
                    "Do not write JSON in your text response."
                )
            except json.JSONDecodeError:
                pass

        return DecisionOutput(
            answer=text
        )

    # =====================================================
    # Safety
    # =====================================================

    def _reject_artifacts(
        self,
        args: dict,
    ) -> None:

        for value in args.values():

            if (
                isinstance(
                    value,
                    str,
                )
                and value.startswith(
                    "art:"
                )
            ):
                raise ValueError(
                    "You attempted to pass an artifact handle ('art:...') to an MCP tool. "
                    "Artifact handles cannot be sent to tools. "
                    "If you need to process the content of an artifact, "
                    "you MUST read it from the ATTACHED ARTIFACTS section of your prompt. "
                    "If the artifact is attached, output a final ANSWER based on its content. "
                    "Do NOT call a tool with the artifact handle."
                )

    # =====================================================
    # Observability
    # =====================================================

    def _observe_router(
        self,
        router: (
            RouterDecision
            | None
        ),
    ) -> None:
        """
        Dashboard visibility.

        No behavioral effect.
        """

        if not router:
            return

        # print(
        #     (
        #         "[decision]"
        #         f"[{router.tier}]"
        #         f" {router.reason}"
        #     )
        # )