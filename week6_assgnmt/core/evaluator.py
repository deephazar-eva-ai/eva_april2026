from core.models import EvaluationResult, RetrievalResult


class Evaluator:
    """
    Evaluates whether retrieved information is relevant.
    """

    def evaluate(self, result: RetrievalResult):
        if not result.documents:
            return EvaluationResult(
                relevant=False,
                confidence=0.0,
                missing_information=True,
                feedback="No documents retrieved",
            )

        avg_score = sum(d.score for d in result.documents) / len(result.documents)

        return EvaluationResult(
            relevant=avg_score > 0.5,
            confidence=avg_score,
            missing_information=avg_score < 0.5,
            feedback="Retrieval successful",
        )