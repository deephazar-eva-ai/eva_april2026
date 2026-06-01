from pathlib import Path
import uuid
import hashlib
import json
import mimetypes
import time

from typing import Any, Literal, Optional

# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field

from core.models import Artifact, MemoryItem



# =========================================================
# Artifact Store
# =========================================================

class ArtifactStore:
    """
    Content-addressable artifact store.

    Storage layout:

        state/artifacts/
            art:abc123.bin
            art:abc123.json

    Design goals:
        - large bytes live outside Memory
        - deduplicate identical content
        - cheap memory retrieval
        - selective attachment into Decision
    """

    def __init__(
        self,
        storage_dir: str = "state/artifacts",
    ):

        self.storage_dir = Path(storage_dir)

        self.storage_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    # =====================================================
    # Helpers
    # =====================================================

    def _hash(
        self,
        blob: bytes,
    ) -> str:

        return hashlib.sha256(
            blob
        ).hexdigest()

    def _artifact_id(
        self,
        sha256: str,
    ) -> str:

        return f"art:{sha256[:12]}"

    def _bin_path(
        self,
        artifact_id: str,
    ) -> Path:

        return (
            self.storage_dir
            / f"{artifact_id}.bin"
        )

    def _meta_path(
        self,
        artifact_id: str,
    ) -> Path:

        return (
            self.storage_dir
            / f"{artifact_id}.json"
        )

    # =====================================================
    # Public API
    # =====================================================

    def put(
        self,
        blob: bytes,
        *,
        content_type: str,
        source: str,
        descriptor: str,
    ) -> str:
        """
        Store bytes.

        Returns:
            artifact handle

        Deduplicates identical blobs.
        """

        sha256 = self._hash(blob)

        artifact_id = self._artifact_id(
            sha256
        )

        bin_path = self._bin_path(
            artifact_id
        )

        meta_path = self._meta_path(
            artifact_id
        )

        # -------------------------------------------------
        # Content-addressable dedupe
        # -------------------------------------------------

        if not bin_path.exists():

            bin_path.write_bytes(blob)

            meta = Artifact(
                artifact_id=artifact_id,
                sha256=sha256,
                size_bytes=len(blob),
                content_type=content_type,
                source=source,
                descriptor=descriptor,
            )

            meta_path.write_text(
                meta.model_dump_json(
                    indent=2
                )
            )

        return artifact_id

    def get_bytes(
        self,
        artifact_id: str,
    ) -> bytes:

        return self._bin_path(
            artifact_id
        ).read_bytes()

    def get_meta(
        self,
        artifact_id: str,
    ) -> Artifact:

        raw = json.loads(
            self._meta_path(
                artifact_id
            ).read_text()
        )

        return Artifact(**raw)

    def exists(
        self,
        artifact_id: str,
    ) -> bool:

        return self._bin_path(
            artifact_id
        ).exists()


# =========================================================
# Example Agent Loop Boundary
# =========================================================

def attach_artifact_if_needed(
    *,
    artifact_store: ArtifactStore,
    memory_item: MemoryItem,
) -> Optional[str]:
    """
    Perception decides attachment.

    Decision sees bytes ONLY if
    Perception explicitly requests them.
    """

    if not memory_item.artifact_id:
        return None

    blob = artifact_store.get_bytes(
        memory_item.artifact_id
    )

    # -----------------------------------------------------
    # Usually decode small textual artifacts
    # -----------------------------------------------------

    try:
        return blob.decode("utf-8")

    except UnicodeDecodeError:
        return (
            f"<binary artifact: "
            f"{memory_item.artifact_id}>"
        )