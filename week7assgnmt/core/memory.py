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
        content = self.storage_path.read_text().strip()
        
        if not content:
            raw = []
        else:
            raw = json.loads(content)

        return [
            MemoryItem(**item)
            for item in raw
        ]

    def _flush(self, memory_list: list[MemoryItem]):
        self.storage_path.write_text(
            json.dumps(
                [
                    item.model_dump()
                    for item
                    in memory_list
                ],
                indent=2,
            )
        )

    def _persist_item(
        self,
        item: MemoryItem,
    ) -> MemoryItem:
        memory = self._load()
        memory.append(item)
        self._flush(memory)

        if item.embedding:
            try:
                from tools.supportingfunc import Session7MemoryIndex
                import numpy as np
                try:
                    index = Session7MemoryIndex.load(768)
                except Exception:
                    index = Session7MemoryIndex(768)
                index.add(np.array([item.embedding], dtype=np.float32), [item.memory_id])
                index.save()
            except Exception as e:
                import logging
                logging.error(f"Failed to update FAISS index during _persist_item: {e}")

        return item

    def _persist_items_batch(
        self,
        items: list[MemoryItem],
    ) -> list[MemoryItem]:
        memory = self._load()
        memory.extend(items)
        self._flush(memory)

        embeddings_to_add = []
        ids_to_add = []

        for item in items:
            if item.embedding:
                embeddings_to_add.append(item.embedding)
                ids_to_add.append(item.memory_id)

        if embeddings_to_add:
            try:
                from tools.supportingfunc import Session7MemoryIndex
                import numpy as np
                try:
                    index = Session7MemoryIndex.load(768)
                except Exception:
                    index = Session7MemoryIndex(768)
                index.add(np.array(embeddings_to_add, dtype=np.float32), ids_to_add)
                index.save()
            except Exception as e:
                import logging
                logging.error(f"Failed to update FAISS index during _persist_items_batch: {e}")

        return items

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

        # ---------------------------------------------
        # Vector Search First
        # ---------------------------------------------
        embedding = self._try_embed(query)
        if embedding:
            try:
                from tools.supportingsearch import MemorySearch
                memory_store = {item.memory_id: item for item in memory}
                searcher = MemorySearch(dimension=768, memory_store=memory_store)
                
                def _filter(item):
                    if kinds and item.kind not in kinds:
                        return False
                    if item.kind == "scratchpad" and current_run_id and getattr(item, "run_id", None) != current_run_id:
                        return False
                    return True
                    
                # Fetch more candidates to account for post-filtering
                candidates = searcher.search(query_embedding=embedding, k=max(top_k * 5, 50), metadata_filter=_filter)
                
                if candidates:
                    results = []
                    for c in candidates:
                        item = c.get("metadata")
                        if item is None:
                            continue
                        item.score = float(c["score"])
                        results.append(item)
                        
                    if current_run_id:
                        for item in results:
                            if getattr(item, "run_id", None) == current_run_id:
                                item.score += 100.0
                                
                    # Ensure all current_run_id items are included, even if FAISS missed them
                    if current_run_id:
                        for item in memory:
                            if getattr(item, "run_id", None) == current_run_id and item not in results:
                                item.score = 100.0
                                results.append(item)
                                
                    results.sort(key=lambda x: x.score, reverse=True)
                    return results[:top_k]
            except Exception as e:
                import logging
                logging.warning(f"Vector search failed, falling back to keyword: {e}")

        # ---------------------------------------------
        # Keyword Search Fallback
        # ---------------------------------------------


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
    # Embed
    # =====================================================

    def _try_embed(self, text: str, task_type: Optional[str] = None) -> Optional[list[float]]:
        import httpx
        import logging
        try:
            payload = {"text": text}
            if task_type:
                payload["task_type"] = task_type
                
            r = httpx.post(
                "http://localhost:8107/v1/embed",
                json=payload,
                timeout=10.0
            )
            r.raise_for_status()
            return r.json().get("embedding")
        except Exception as e:
            logging.warning(f"Embedding failed: {e}")
            return None

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

        descriptor = raw_text[:80]
        embedding = None if kind == "scratchpad" else self._try_embed(descriptor)

        item = MemoryItem(
            memory_id=str(uuid.uuid4()),
            kind=kind,
            source=source,
            raw_text=raw_text,
            descriptor=descriptor,
            keywords=list(
                self._tokenize(raw_text)
            ),
            structured_value={},
            run_id=run_id,
            goal_id=goal_id,
            embedding=embedding,
        )

        return self._persist_item(item)

    # =====================================================
    # add_fact()
    # =====================================================

    def add_fact(
        self,
        descriptor: str,
        *,
        raw_text: str,
        keywords: list[str],
        structured_value: dict,
        source: str,
        run_id: str,
        goal_id: Optional[str] = None
    ) -> MemoryItem:
        """
        Direct fact insertion (e.g. for RAG indexing).
        No LLM classification required.
        """
        embedding = self._try_embed(raw_text, task_type="retrieval_document")

        item = MemoryItem(
            memory_id=str(uuid.uuid4()),
            kind="fact",
            source=source,
            raw_text=raw_text,
            descriptor=descriptor,
            keywords=[k.lower() for k in keywords],
            structured_value=structured_value,
            run_id=run_id,
            goal_id=goal_id,
            embedding=embedding,
        )

        return self._persist_item(item)

    # =====================================================
    # add_facts_batch()
    # =====================================================

    def add_facts_batch(
        self,
        facts: list[dict],
    ) -> list[MemoryItem]:
        """
        Batch fact insertion for multiple chunks efficiently.
        No LLM classification required.
        `facts` should be a list of dictionaries, each containing:
        - descriptor: str
        - raw_text: str
        - keywords: list[str]
        - structured_value: dict
        - source: str
        - run_id: str
        - goal_id: Optional[str]
        """
        items = []
        for fact in facts:
            embedding = self._try_embed(fact["raw_text"], task_type="retrieval_document")
            item = MemoryItem(
                memory_id=str(uuid.uuid4()),
                kind="fact",
                source=fact["source"],
                raw_text=fact["raw_text"],
                descriptor=fact["descriptor"],
                keywords=[k.lower() for k in fact["keywords"]],
                structured_value=fact["structured_value"],
                run_id=fact["run_id"],
                goal_id=fact.get("goal_id"),
                embedding=embedding,
            )
            items.append(item)

        return self._persist_items_batch(items)

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

        descriptor = (
            f"{tool_name}"
            f" -> artifact:{artifact_id}"
        )

        embedding = self._try_embed(descriptor)

        item = MemoryItem(
            memory_id=str(uuid.uuid4()),
            kind="tool_outcome",
            source="tool_dispatch",
            raw_text=result_text,
            descriptor=descriptor,
            keywords=keywords,
            structured_value={
                "tool_name": tool_name,
                "arguments": arguments,
                "artifact_id": artifact_id,
            },
            run_id=run_id,
            goal_id=goal_id,
            embedding=embedding,
        )

        return self._persist_item(item)

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

        self._flush([])

        # Clear FAISS index files
        index_faiss = self.storage_path.parent / "index.faiss"
        if index_faiss.exists():
            index_faiss.unlink()
            
        index_ids = self.storage_path.parent / "index_ids.json"
        if index_ids.exists():
            index_ids.unlink()

