"""Admission checks for model-written decision problems, not a semantic router."""
import unicodedata
from .models import DecisionAwarenessTrace, DecisionMode


def normalized_text(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def question_issue(trace: DecisionAwarenessTrace, source_text: str | None = None) -> str | None:
    if trace.mode is DecisionMode.NONE or trace.decision_kind != "NEW":
        return "not_new_decision"
    if not trace.decision_question or not trace.decision_question.strip():
        return "missing_decision_question"
    problem = normalized_text(trace.decision_question)
    if len(problem) < 4:
        return "invalid_decision_question"
    if source_text and problem in normalized_text(source_text):
        return "copied_user_text"
    if trace.agent_recommendation and problem == normalized_text(trace.agent_recommendation):
        return "recommendation_as_question"
    return None
