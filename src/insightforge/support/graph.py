import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from insightforge.config import Settings, get_settings
from insightforge.services.guardrails import validate_query, wrap_untrusted
from insightforge.services.llm import LLM, build_llm
from insightforge.services.retriever import KnowledgeBase
from insightforge.support.models import IntentResult, ResponseReview, ServiceDecision
from insightforge.support.prompts import DECISION_SYSTEM, INTENT_SYSTEM, REVIEW_SYSTEM
from insightforge.support.state import SupportState
from insightforge.support.store import CommerceStore


@dataclass
class SupportDependencies:
    llm: LLM
    store: CommerceStore
    policies: KnowledgeBase
    settings: Settings
    today: Callable[[], date] = date.today


def seed_policies(kb: KnowledgeBase) -> None:
    kb.ingest_text(
        "签收后 7 天内，商品完好且配件齐全可申请无理由退款。退款金额不得超过实付金额。"
        "已超过 7 天或商品存在人为损坏时转人工售后审核。",
        "policy://returns-v3",
        "退换货政策 v3（2026-07-01 生效）",
    )
    kb.ingest_text(
        "物流超过承诺日期 48 小时仍未送达时创建物流异常工单。运输中状态应先告知运单号，"
        "不得直接承诺退款。",
        "policy://logistics-v2",
        "物流异常处理政策 v2",
    )
    kb.ingest_text(
        "自动退款金额大于 200 元、同一订单重复退款或高风险投诉必须由人工审批。"
        "所有执行动作必须携带幂等键并记录审计日志。",
        "policy://risk-v1",
        "售后风险控制政策 v1",
    )


def build_support_graph(deps: SupportDependencies, checkpointer=None):
    def guardrail(state: SupportState) -> dict:
        checked = validate_query(state.get("message", ""), deps.settings.max_query_chars)
        if not checked.allowed:
            return {"error": checked.reason, "final_reply": f"无法处理该请求：{checked.reason}"}
        return {"sanitized_message": checked.sanitized_text}

    def understand(state: SupportState) -> dict:
        intent = deps.llm.structured(
            INTENT_SYSTEM, f"用户消息：{state['sanitized_message']}", IntentResult
        )
        return {"intent": intent}

    def load_order(state: SupportState) -> dict:
        intent = state["intent"]
        if intent.needs_order and not intent.order_id:
            return {"final_reply": "请提供 EC 开头的订单号，例如 EC2026001，我才能继续处理。"}
        order = deps.store.get_order(intent.order_id) if intent.order_id else None
        if intent.order_id and not order:
            return {"final_reply": f"没有找到订单 {intent.order_id}，请检查订单号是否正确。"}
        return {"order": order}

    def retrieve_policy(state: SupportState) -> dict:
        query = f"{state['intent'].intent} {state['sanitized_message']}"
        return {"policies": deps.policies.search(query, limit=5)}

    def decide(state: SupportState) -> dict:
        evidence = "\n".join(
            f"{item.id} {item.title}\n{wrap_untrusted(item.content)}"
            for item in state.get("policies", [])
        )
        user = (
            f"用户诉求：{state['sanitized_message']}\n"
            f"意图：{state['intent'].model_dump_json()}\n"
            f"订单：{state['order'].model_dump_json() if state.get('order') else '无'}\n"
            f"政策：{evidence or '未检索到'}"
        )
        decision = deps.llm.structured(DECISION_SYSTEM, user, ServiceDecision)
        if state.get("order") and decision.refund_amount > state["order"].amount:
            decision.refund_amount = state["order"].amount
            decision.risk_level = "high"
        if decision.action == "refund" and state.get("order") and state["order"].delivered_at:
            delivered = datetime.strptime(state["order"].delivered_at, "%Y-%m-%d").date()
            if (deps.today() - delivered).days > 7:
                decision.action = "create_ticket"
                decision.risk_level = "high"
                decision.reason = "订单已超过 7 天无理由退货期，转人工工单审核"
                decision.reply = "订单已超过 7 天无理由退货期，我会创建工单进行人工审核。"
        needs_human = decision.action == "refund" and (
            decision.refund_amount > 200 or decision.risk_level == "high"
        )
        return {"decision": decision, "needs_human": needs_human}

    def review(state: SupportState) -> dict:
        payload = json.dumps(
            {
                "order": state["order"].model_dump() if state.get("order") else None,
                "decision": state["decision"].model_dump(),
                "policy_ids": [item.id for item in state.get("policies", [])],
            },
            ensure_ascii=False,
        )
        result = deps.llm.structured(REVIEW_SYSTEM, payload, ResponseReview)
        update = {"review": result}
        if not result.passed or not result.safe_to_execute:
            update["final_reply"] = "风控检查未通过，系统没有执行任何售后操作。"
        return update

    def approval(state: SupportState) -> dict:
        if not state.get("needs_human"):
            return {"approval_status": "not_required"}
        decision = interrupt(
            {
                "type": "refund_approval",
                "order": state["order"].model_dump(mode="json") if state.get("order") else None,
                "decision": state["decision"].model_dump(mode="json"),
                "message": "高金额退款需要人工审批",
            }
        )
        approved = isinstance(decision, dict) and bool(decision.get("approved"))
        return {"approval_status": "approved" if approved else "rejected"}

    def execute(state: SupportState) -> dict:
        decision = state["decision"]
        if decision.action == "answer":
            return {}
        result = deps.store.execute(
            thread_id=state["thread_id"],
            order=state.get("order"),
            action=decision.action,
            amount=decision.refund_amount,
            reason=decision.reason,
        )
        return {"action_result": result}

    def respond(state: SupportState) -> dict:
        if state.get("approval_status") == "rejected":
            return {"final_reply": "退款申请未通过人工审批，已保留本次审核记录。"}
        order = state.get("order")
        order_text = ""
        if order:
            order_text = (
                f"\n\n订单：{order.order_id}｜{order.product_name}｜状态：{order.status}"
                + (f"｜运单号：{order.tracking_no}" if order.tracking_no else "")
            )
        action = state.get("action_result")
        action_text = (
            f"\n\n处理结果：{action.message}\n业务流水号：{action.reference_id}" if action else ""
        )
        citations = " ".join(state["decision"].policy_citations)
        cite_text = f"\n\n政策依据：{citations}" if citations else ""
        return {"final_reply": state["decision"].reply + order_text + action_text + cite_text}

    def route_guard(state: SupportState) -> str:
        return "end" if state.get("error") else "understand"

    def route_order(state: SupportState) -> str:
        return "end" if state.get("final_reply") else "retrieve_policy"

    def route_review(state: SupportState) -> str:
        if not state["review"].passed or not state["review"].safe_to_execute:
            return "end"
        return "approval"

    def route_approval(state: SupportState) -> str:
        return "respond" if state.get("approval_status") == "rejected" else "execute"

    workflow = StateGraph(SupportState)
    for name, node in (
        ("guardrail", guardrail),
        ("understand", understand),
        ("load_order", load_order),
        ("retrieve_policy", retrieve_policy),
        ("decide", decide),
        ("review", review),
        ("approval", approval),
        ("execute", execute),
        ("respond", respond),
    ):
        workflow.add_node(name, node)
    workflow.add_edge(START, "guardrail")
    workflow.add_conditional_edges(
        "guardrail", route_guard, {"end": END, "understand": "understand"}
    )
    workflow.add_edge("understand", "load_order")
    workflow.add_conditional_edges(
        "load_order", route_order, {"end": END, "retrieve_policy": "retrieve_policy"}
    )
    workflow.add_edge("retrieve_policy", "decide")
    workflow.add_edge("decide", "review")
    workflow.add_conditional_edges("review", route_review, {"end": END, "approval": "approval"})
    workflow.add_conditional_edges(
        "approval", route_approval, {"respond": "respond", "execute": "execute"}
    )
    workflow.add_edge("execute", "respond")
    workflow.add_edge("respond", END)
    return workflow.compile(checkpointer=checkpointer or InMemorySaver())


def default_support_dependencies() -> SupportDependencies:
    settings = get_settings()
    store = CommerceStore(settings.database_path)
    store.seed_demo_orders()
    policies = KnowledgeBase(settings.database_path)
    seed_policies(policies)
    return SupportDependencies(build_llm(settings), store, policies, settings)


support_graph = build_support_graph(default_support_dependencies())
