from pathlib import Path
import json
import faiss
import numpy as np


class Session7MemoryIndex:

    INDEX_PATH = Path("state/index.faiss")
    IDS_PATH = Path("state/index_ids.json")

    def __init__(
        self,
        dimension: int,
    ):
        self.dimension = dimension

        self.index = (
            faiss.IndexFlatIP(
                dimension
            )
        )

        self.index_ids: list[str] = []

    @staticmethod
    def _normalize(
        vectors: np.ndarray,
    ):

        vectors = (
            vectors.astype(
                np.float32
            ).copy()
        )

        faiss.normalize_L2(
            vectors
        )

        return vectors

    def add(
        self,
        vectors: np.ndarray,
        ids: list[str],
    ):

        if len(vectors) != len(ids):
            raise ValueError(
                "vectors and ids must match"
            )

        vectors = (
            self._normalize(
                vectors
            )
        )

        self.index.add(
            vectors
        )

        self.index_ids.extend(
            ids
        )

    def search(
        self,
        query: np.ndarray,
        k: int,
    ):

        query = (
            np.asarray(
                query,
                dtype=np.float32,
            )
            .reshape(1, -1)
        )

        query = self._normalize(
            query
        )

        scores, pos = (
            self.index.search(
                query,
                k,
            )
        )

        return [
            {
                "memory_id":
                    self.index_ids[
                        p
                    ],
                "score":
                    float(s),
            }
            for s, p in zip(
                scores[0],
                pos[0],
            )
            if p >= 0
        ]

    def save(self):

        self.INDEX_PATH.parent.mkdir(
            exist_ok=True
        )

        faiss.write_index(
            self.index,
            str(
                self.INDEX_PATH
            ),
        )

        self.IDS_PATH.write_text(
            json.dumps(
                self.index_ids
            )
        )

    @classmethod
    def load(
        cls,
        dimension: int,
    ):

        obj = cls(
            dimension
        )

        if not cls.INDEX_PATH.exists() or not cls.IDS_PATH.exists():
            return obj

        obj.index = (
            faiss.read_index(
                str(
                    cls.INDEX_PATH
                )
            )
        )

        obj.index_ids = json.loads(
            cls.IDS_PATH.read_text()
        )

        return obj