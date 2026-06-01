from tools.supportingfunc import Session7MemoryIndex
class MemorySearch:

    def __init__(
        self,
        dimension: int,
        memory_store: dict,
    ):
        self.dimension = dimension
        self.memory_store = (
            memory_store
        )

    def search(
        self,
        query_embedding,
        k=10,
        metadata_filter=None,
    ):

        index = (
            Session7MemoryIndex
            .load(
                self.dimension
            )
        )

        candidates = (
            index.search(
                query_embedding,
                k,
            )
        )

        results = []

        for c in candidates:

            metadata = (
                self.memory_store.get(
                    c["memory_id"]
                )
            )

            if metadata is None:
                continue

            if (
                metadata_filter
                and not metadata_filter(
                    metadata
                )
            ):
                continue

            results.append(
                {
                    **c,
                    "metadata":
                        metadata,
                }
            )

        return results


# search = MemorySearch(
#     dimension=768,
#     memory_store=memory_db,
# )

# results = search.search(
#     query_embedding,
#     k=10,
#     metadata_filter=lambda x:
#         x["author"]
#         == "paper_3"
# )        