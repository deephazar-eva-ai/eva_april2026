# =========================================================
# Action
# =========================================================

from core.artifacts import ArtifactStore
from core.models import ClientSession, ToolCall, MCPResult

class Action:
    """
    Pure dispatch.

    Input:
        ToolCall

    Output:
        (
            descriptor,
            artifact_id
        )

    No LLM.
    """

    ARTIFACT_THRESHOLD_BYTES = (
        4 * 1024
    )

    PREVIEW_BYTES = 256

    def __init__(
        self,
        artifact_store: ArtifactStore,
    ):

        self.artifacts = (
            artifact_store
        )

    # =====================================================
    # Public API
    # =====================================================

    async def execute(
        self,
        session: ClientSession,
        tool_call: ToolCall,
    ) -> tuple[
        str,
        str | None,
    ]:
        """
        Execute one MCP tool.

        Never calls LLM.
        """

        # --------------------------------------
        # Block art: misuse
        # --------------------------------------

        error = (
            self._reject_artifacts(
                tool_call
            )
        )

        if error:

            return (
                error,
                None,
            )

        try:

            result = (
                await session.call_tool(
                    tool_call.name,
                    tool_call.arguments,
                )
            )

        except Exception as e:

            return (
                (
                    f"[tool error] "
                    f"{tool_call.name}: "
                    f"{e}"
                ),
                None,
            )

        # --------------------------------------
        # Collapse MCP blocks
        # --------------------------------------

        text = (
            self._collapse(
                result
            )
        )

        payload = text.encode(
            "utf-8",
            errors="replace",
        )

        # --------------------------------------
        # Small payload
        # --------------------------------------

        if (
            len(payload)
            <
            self.ARTIFACT_THRESHOLD_BYTES
        ):

            return (
                text,
                None,
            )

        # --------------------------------------
        # Artifact path
        # --------------------------------------

        preview = (
            text[
                : self.PREVIEW_BYTES
            ]
            .replace(
                "\n",
                " ",
            )
            .strip()
        )

        descriptor = (
            f"[artifact "
            f"<pending>, "
            f"{len(payload)} bytes] "
            f"preview: "
            f"{preview}"
        )

        artifact_id = (
            self.artifacts.put(
                payload,
                content_type=(
                    "text/plain"
                ),
                source=(
                    tool_call.name
                ),
                descriptor=(
                    descriptor
                ),
            )
        )

        descriptor = (
            f"[artifact "
            f"{artifact_id}, "
            f"{len(payload)} bytes] "
            f"preview: "
            f"{preview}"
        )

        return (
            descriptor,
            artifact_id,
        )

    # =====================================================
    # Artifact Guard
    # =====================================================

    def _reject_artifacts(
        self,
        tool_call: ToolCall,
    ) -> str | None:
        """
        Reject art: dispatch.

        Return error text
        instead of raising.
        """

        for value in (
            tool_call
            .arguments
            .values()
        ):

            if (
                isinstance(
                    value,
                    str,
                )
                and value.startswith(
                    "art:"
                )
            ):

                return (
                    "[dispatch blocked] "
                    "artifact handles "
                    "are internal "
                    "references, not "
                    "file paths or URLs"
                )

        return None

    # =====================================================
    # MCP Normalization
    # =====================================================

    def _collapse(
        self,
        result: MCPResult,
    ) -> str:
        """
        Collapse content blocks.
        """

        if not result.content:
            return ""

        parts = []

        for block in (
            result.content
        ):

            if (
                block.text
            ):

                parts.append(
                    block.text
                )

        return (
            "\n"
            .join(parts)
            .strip()
        )