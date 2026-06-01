# =========================================================
# Persistence Model
# =========================================================
#
# All memory items persist inside:
#
#     state/memory.json
#
# The same file is reused across runs.
#
# Consequences:
#
# - preferences persist
# - facts persist
# - tool outcomes persist
# - scratchpads may persist unless cleaned
#
# Clearing the file resets the agent.
#
# =========================================================


from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field
from core.models import MemoryItem, MemoryKind

# =========================================================
# Memory Service
# =========================================================

class MemoryService:
    """
    Unified persistent memory system.

    All memory kinds share:
        - same storage
        - same schema
        - same retrieval interface

    Scratchpad is only a behavioral distinction.
    """

    STOPWORDS = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "to",
        "of",
        "and",
        "in",
        "for",
        "on",
        "with",
    }

    # =====================================================
    # Persistence
    # =====================================================

    def __init__(
        self,
        storage_path: str = "state/memory.json",
    ):

        self.storage_path = Path(storage_path)

        self.storage_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if not self.storage_path.exists():
            self.storage_path.write_text("[]")

        self._cache: Optional[
            list[MemoryItem]
        ] = None

    def _load(self) -> list[MemoryItem]:

        if self._cache is not None:
            return self._cache

        content = self.storage_path.read_text().strip()
        
        if not content:
            raw = []
        else:
            raw = json.loads(content)

        self._cache = [
            MemoryItem(**item)
            for item in raw
        ]

        return self._cache

    def _flush(self):

        if self._cache is None:
            return

        self.storage_path.write_text(
            json.dumps(
                [
                    item.model_dump()
                    for item
                    in self._cache
                ],
                indent=2,
            )
        )

    def _append(
        self,
        item: MemoryItem,
    ):

        memory = self._load()

        memory.append(item)

        self._flush()

    # =====================================================
    # Tokenization
    # =====================================================

    def _tokenize(
        self,
        text: str,
    ) -> set[str]:

        return {
            token.lower().strip(
                ".,!?()[]{}:"
            )
            for token in text.split()
            if token.lower()
            not in self.STOPWORDS
        }

    # =====================================================
    # Read
    # =====================================================

    def read(
        self,
        query: str,
        history: Optional[
            list[dict]
        ] = None,
        kinds: Optional[
            list[MemoryKind]
        ] = None,
        top_k: int = 8,
        current_run_id: Optional[
            str
        ] = None,
    ) -> list[MemoryItem]:
        """
        Cheap keyword retrieval.

        Scratchpad behavior:
            future runs ignore old scratchpads
        """

        memory = self._load()

        query_terms = self._tokenize(
            query
        )

        history_terms = set()

        if history:

            history_text = " ".join(
                item.get(
                    "descriptor",
                    "",
                )
                for item in history
            )

            history_terms = self._tokenize(
                history_text
            )

        results = []

        for item in memory:

            # ---------------------------------------------
            # Optional kind filter
            # ---------------------------------------------

            if (
                kinds
                and item.kind not in kinds
            ):
                continue

            # ---------------------------------------------
            # Scratchpad visibility rule
            # ---------------------------------------------

            if (
                item.kind == "scratchpad"
                and current_run_id
                and item.run_id
                != current_run_id
            ):
                continue

            searchable_terms = set(
                keyword.lower()
                for keyword
                in item.keywords
            )

            descriptor_terms = (
                self._tokenize(
                    item.descriptor
                )
            )

            query_overlap = len(
                query_terms.intersection(
                    searchable_terms
                )
            )

            history_overlap = len(
                history_terms.intersection(
                    descriptor_terms
                )
            )

            score = (
                query_overlap
                + history_overlap
            )
            
            # Ensure recent tool outcomes are always retrieved
            if current_run_id and getattr(item, "run_id", None) == current_run_id:
                score += 100

            if score <= 0:
                continue

            item.score = float(score)

            results.append(item)

        results.sort(
            key=lambda x: x.score,
            reverse=True,
        )

        return results[:top_k]

    # =====================================================
    # Filter
    # =====================================================

    def filter(
        self,
        kinds: Optional[
            list[MemoryKind]
        ] = None,
        goal_id: Optional[str] = None,
        recent: Optional[int] = None,
    ) -> list[MemoryItem]:

        memory = self._load()

        results = []

        for item in memory:

            if (
                kinds
                and item.kind not in kinds
            ):
                continue

            if (
                goal_id
                and item.goal_id != goal_id
            ):
                continue

            results.append(item)

        results.sort(
            key=lambda x: x.created_at,
            reverse=True,
        )

        if recent:
            results = results[:recent]

        return results

    # =====================================================
    # remember()
    # =====================================================

    def remember(
        self,
        raw_text: str,
        source: str,
        run_id: str,
        goal_id: Optional[
            str
        ] = None,
    ) -> MemoryItem:
        """
        Ambiguous free-form write.

        Real implementation:
            one LLM classification call

        The classifier extracts:
            - kind
            - keywords
            - descriptor
            - structured_value
        """

        # -------------------------------------------------
        # Placeholder classification
        # -------------------------------------------------

        text = raw_text.lower()

        if "prefer" in text:
            kind = "preference"

        elif (
            "temporary"
            in text
            or "working"
            in text
        ):
            kind = "scratchpad"

        else:
            kind = "fact"

        item = MemoryItem(
            memory_id=str(uuid.uuid4()),
            kind=kind,
            source=source,
            raw_text=raw_text,
            descriptor=raw_text[:80],
            keywords=list(
                self._tokenize(raw_text)
            ),
            structured_value={},
            run_id=run_id,
            goal_id=goal_id,
        )

        self._append(item)

        return item

    # =====================================================
    # record_outcome()
    # =====================================================

    def record_outcome(
        self,
        tool_call: Any,
        result_text: str,
        artifact_id: Optional[
            str
        ],
        run_id: str,
        goal_id: Optional[
            str
        ] = None,
    ) -> MemoryItem:
        """
        Tool outcome insertion.

        No LLM required.
        """

        if isinstance(tool_call, dict):
            tool_name = tool_call.get("name") or tool_call.get("tool_name", "unknown_tool")
            arguments = tool_call.get("arguments", {})
        elif isinstance(tool_call, str):
            tool_name = tool_call
            arguments = {}
        else:
            tool_name = tool_call.name
            arguments = tool_call.arguments

        arg_tokens = []

        for value in arguments.values():
            arg_tokens.extend(
                str(value).split()
            )

        keywords = [
            tool_name,
            *arg_tokens,
        ]

        item = MemoryItem(
            memory_id=str(uuid.uuid4()),
            kind="tool_outcome",
            source="tool_dispatch",
            raw_text=result_text,
            descriptor=(
                f"{tool_name}"
                f" -> artifact:{artifact_id}"
            ),
            keywords=keywords,
            structured_value={
                "tool_name": tool_name,
                "arguments": arguments,
                "artifact_id": artifact_id,
            },
            run_id=run_id,
            goal_id=goal_id,
        )

        self._append(item)

        return item

    # =====================================================
    # Promotion
    # =====================================================

    def promote(
        self,
        memory_id: str,
        new_kind: Literal[
            "fact",
            "preference",
        ],
    ):
        """
        Promote scratchpad into
        durable memory.
        """

        memory = self._load()

        for item in memory:

            if item.memory_id == memory_id:
                item.kind = new_kind

        self._flush()

    # =====================================================
    # Reset
    # =====================================================

    def reset(self):
        """
        Clear persistent state.

        Useful for recurring assignments/tests.
        """

        self._cache = []

        self._flush()
