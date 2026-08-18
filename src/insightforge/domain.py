from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl


class SourceType(StrEnum):
    KNOWLEDGE_BASE = "knowledge_base"
    WEB = "web"
    MODEL = "model"


class PlanStep(BaseModel):
    id: str = Field(description="Short stable id, e.g. S1")
    title: str
    objective: str
    search_query: str
    needs_web: bool = False


class ResearchPlan(BaseModel):
    goal: str
    steps: list[PlanStep] = Field(min_length=1, max_length=6)
    success_criteria: list[str] = Field(min_length=1, max_length=6)


class Evidence(BaseModel):
    id: str
    title: str
    content: str
    source_type: SourceType
    url: HttpUrl | None = None
    score: float = Field(default=0.5, ge=0, le=1)

    def citation(self) -> str:
        return f"[{self.id}]"


class QualityReview(BaseModel):
    score: int = Field(ge=0, le=100)
    passed: bool
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    follow_up_queries: list[str] = Field(default_factory=list, max_length=4)


class ResearchResult(BaseModel):
    thread_id: str
    status: str
    report: str = ""
    quality_score: int = 0
    evidence_count: int = 0
    iterations: int = 0
    plan: ResearchPlan | None = None
