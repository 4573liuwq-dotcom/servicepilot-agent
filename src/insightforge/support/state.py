from typing import TypedDict

from insightforge.domain import Evidence
from insightforge.support.models import (
    ActionResult,
    IntentResult,
    Order,
    ResponseReview,
    ServiceDecision,
)


class SupportState(TypedDict, total=False):
    thread_id: str
    message: str
    sanitized_message: str
    intent: IntentResult
    order: Order | None
    policies: list[Evidence]
    decision: ServiceDecision
    review: ResponseReview
    needs_human: bool
    approval_status: str
    action_result: ActionResult
    final_reply: str
    error: str
