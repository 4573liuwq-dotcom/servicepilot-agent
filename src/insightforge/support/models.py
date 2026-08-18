from enum import StrEnum

from pydantic import BaseModel, Field


class Intent(StrEnum):
    ORDER_STATUS = "order_status"
    LOGISTICS = "logistics"
    RETURN_REFUND = "return_refund"
    COMPLAINT = "complaint"
    PRODUCT_HELP = "product_help"
    OTHER = "other"


class IntentResult(BaseModel):
    intent: Intent
    order_id: str | None = None
    needs_order: bool = False
    summary: str


class Order(BaseModel):
    order_id: str
    customer_name: str
    product_name: str
    amount: float
    status: str
    paid_at: str
    delivered_at: str | None = None
    tracking_no: str | None = None


class ServiceDecision(BaseModel):
    action: str = Field(description="answer, create_ticket, or refund")
    reason: str
    reply: str
    refund_amount: float = Field(default=0, ge=0)
    risk_level: str = Field(default="low", description="low, medium, or high")
    policy_citations: list[str] = Field(default_factory=list)


class ResponseReview(BaseModel):
    passed: bool
    policy_grounded: bool
    safe_to_execute: bool
    issues: list[str] = Field(default_factory=list)


class ActionResult(BaseModel):
    action: str
    success: bool
    reference_id: str = ""
    message: str


class SupportResult(BaseModel):
    thread_id: str
    status: str
    reply: str = ""
    intent: Intent | None = None
    order: Order | None = None
    decision: ServiceDecision | None = None
    action_result: ActionResult | None = None
