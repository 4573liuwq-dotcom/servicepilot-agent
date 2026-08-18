from typing import TypedDict

from insightforge.domain import Evidence, QualityReview, ResearchPlan


class ResearchState(TypedDict, total=False):
    query: str
    sanitized_query: str
    plan: ResearchPlan
    evidence: list[Evidence]
    draft: str
    review: QualityReview
    final_report: str
    iteration: int
    max_iterations: int
    quality_threshold: int
    require_approval: bool
    approval_status: str
    approval_feedback: str
    error: str
    events: list[str]
