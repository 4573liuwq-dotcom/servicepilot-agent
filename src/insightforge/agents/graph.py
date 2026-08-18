import json
import logging
from dataclasses import dataclass

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from insightforge.agents.prompts import (
    ANALYST_SYSTEM,
    CRITIC_SYSTEM,
    FINALIZER_SYSTEM,
    PLANNER_SYSTEM,
)
from insightforge.agents.state import ResearchState
from insightforge.config import Settings, get_settings
from insightforge.domain import Evidence, QualityReview, ResearchPlan
from insightforge.services.guardrails import validate_query, wrap_untrusted
from insightforge.services.llm import LLM, build_llm
from insightforge.services.retriever import KnowledgeBase
from insightforge.services.search import WebSearch

logger = logging.getLogger(__name__)


@dataclass
class AgentDependencies:
    llm: LLM
    knowledge_base: KnowledgeBase
    web_search: WebSearch
    settings: Settings


def _evidence_text(items: list[Evidence]) -> str:
    if not items:
        return "（当前没有检索到可用证据）"
    return "\n\n".join(
        f"ID: {item.id}\n标题: {item.title}\n类型: {item.source_type}\n"
        f"可信度: {item.score:.2f}\n{wrap_untrusted(item.content)}"
        for item in items
    )


def build_graph(deps: AgentDependencies, checkpointer=None):
    """Build the explicit, inspectable LangGraph workflow."""

    def guardrail_node(state: ResearchState) -> dict:
        result = validate_query(state.get("query", ""), deps.settings.max_query_chars)
        if not result.allowed:
            return {
                "error": result.reason,
                "final_report": f"请求被安全护栏拒绝：{result.reason}",
                "events": ["guardrail:blocked"],
            }
        return {
            "sanitized_query": result.sanitized_text,
            "iteration": 0,
            "events": ["guardrail:passed"],
        }

    def planner_node(state: ResearchState) -> dict:
        plan = deps.llm.structured(
            PLANNER_SYSTEM,
            f"用户问题：{state['sanitized_query']}",
            ResearchPlan,
        )
        return {"plan": plan, "events": [*state.get("events", []), "planner:completed"]}

    def approval_node(state: ResearchState) -> dict:
        if not state.get("require_approval", False):
            return {"approval_status": "auto_approved"}
        decision = interrupt(
            {
                "type": "plan_approval",
                "message": "请审批研究计划",
                "plan": state["plan"].model_dump(mode="json"),
            }
        )
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else False
        return {
            "approval_status": "approved" if approved else "rejected",
            "approval_feedback": decision.get("feedback", "") if isinstance(decision, dict) else "",
            "final_report": "研究计划未获批准。" if not approved else "",
        }

    def researcher_node(state: ResearchState) -> dict:
        collected = list(state.get("evidence", []))
        queries = [step.search_query for step in state["plan"].steps]
        review = state.get("review")
        if review:
            queries.extend(review.follow_up_queries)

        events = [*state.get("events", []), f"researcher:iteration_{state['iteration']}"]
        for query in dict.fromkeys(queries):
            collected.extend(deps.knowledge_base.search(query, limit=4))

        web_queries = [step.search_query for step in state["plan"].steps if step.needs_web]
        if review:
            web_queries.extend(review.follow_up_queries)
        if deps.web_search.enabled:
            for query in dict.fromkeys(web_queries):
                try:
                    collected.extend(deps.web_search.search(query, limit=3))
                except Exception as exc:  # external search must degrade gracefully
                    logger.warning("web_search_failed", extra={"query": query, "error": str(exc)})
                    events.append("researcher:web_search_degraded")

        deduplicated = {item.id: item for item in collected}
        ranked = sorted(deduplicated.values(), key=lambda item: item.score, reverse=True)[:24]
        return {"evidence": ranked, "events": events}

    def analyst_node(state: ResearchState) -> dict:
        user = (
            f"问题：{state['sanitized_query']}\n\n"
            f"研究计划：{state['plan'].model_dump_json()}\n\n"
            f"证据：\n{_evidence_text(state.get('evidence', []))}"
        )
        draft = deps.llm.text(ANALYST_SYSTEM, user)
        return {"draft": draft, "events": [*state.get("events", []), "analyst:completed"]}

    def critic_node(state: ResearchState) -> dict:
        user = (
            f"问题：{state['sanitized_query']}\n\n"
            f"成功标准：{json.dumps(state['plan'].success_criteria, ensure_ascii=False)}\n\n"
            f"证据 ID：{[item.id for item in state.get('evidence', [])]}\n\n"
            f"待审草稿：\n{state['draft']}"
        )
        review = deps.llm.structured(CRITIC_SYSTEM, user, QualityReview)
        if review.score < state.get("quality_threshold", 80):
            review.passed = False
        return {
            "review": review,
            "iteration": state.get("iteration", 0) + 1,
            "events": [*state.get("events", []), f"critic:score_{review.score}"],
        }

    def finalizer_node(state: ResearchState) -> dict:
        review = state.get("review")
        user = (
            f"问题：{state['sanitized_query']}\n\n"
            f"计划：{state['plan'].model_dump_json()}\n\n"
            f"证据：\n{_evidence_text(state.get('evidence', []))}\n\n"
            f"分析草稿：\n{state.get('draft', '')}\n\n"
            f"质量审计：{review.model_dump_json() if review else '无'}"
        )
        report = deps.llm.text(FINALIZER_SYSTEM, user)
        return {
            "final_report": report,
            "events": [*state.get("events", []), "finalizer:completed"],
        }

    def guard_route(state: ResearchState) -> str:
        return "blocked" if state.get("error") else "planner"

    def approval_route(state: ResearchState) -> str:
        return "researcher" if state.get("approval_status") != "rejected" else "rejected"

    def quality_route(state: ResearchState) -> str:
        review = state["review"]
        if review.passed or state["iteration"] >= state.get("max_iterations", 2):
            return "finalizer"
        return "researcher"

    workflow = StateGraph(ResearchState)
    workflow.add_node("guardrail", guardrail_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("approval", approval_node)
    workflow.add_node("researcher", researcher_node)
    workflow.add_node("analyst", analyst_node)
    workflow.add_node("critic", critic_node)
    workflow.add_node("finalizer", finalizer_node)

    workflow.add_edge(START, "guardrail")
    workflow.add_conditional_edges("guardrail", guard_route, {"blocked": END, "planner": "planner"})
    workflow.add_edge("planner", "approval")
    workflow.add_conditional_edges(
        "approval", approval_route, {"researcher": "researcher", "rejected": END}
    )
    workflow.add_edge("researcher", "analyst")
    workflow.add_edge("analyst", "critic")
    workflow.add_conditional_edges(
        "critic", quality_route, {"researcher": "researcher", "finalizer": "finalizer"}
    )
    workflow.add_edge("finalizer", END)
    return workflow.compile(checkpointer=checkpointer or InMemorySaver())


def default_dependencies() -> AgentDependencies:
    settings = get_settings()
    tavily_key = settings.tavily_api_key.get_secret_value() if settings.tavily_api_key else None
    return AgentDependencies(
        llm=build_llm(settings),
        knowledge_base=KnowledgeBase(settings.database_path),
        web_search=WebSearch(tavily_key),
        settings=settings,
    )


# LangGraph Studio discovers this exported graph through langgraph.json.
graph = build_graph(default_dependencies())
