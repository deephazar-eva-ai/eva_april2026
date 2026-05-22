from typing import List
from core.models import RetrievalResult, FinalResponse


class ResponseGenerator:
    def generate(self, results: List[RetrievalResult]):
        answer_parts = []
        references = []

        for result in results:
            for doc in result.documents:
                answer_parts.append(doc.content)
                references.append(doc.source)

        answer = "\n".join(answer_parts)

        return FinalResponse(
            answer=answer,
            references=list(set(references)),
        )