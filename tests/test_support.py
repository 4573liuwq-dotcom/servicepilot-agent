from datetime import date
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from insightforge.config import Settings
from insightforge.services.llm import DemoLLM
from insightforge.services.retriever import KnowledgeBase
from insightforge.support.graph import SupportDependencies, build_support_graph, seed_policies
from insightforge.support.store import CommerceStore

TEST_TODAY = date(2026, 8, 10)


def make_support_graph(tmp_path: Path):
    settings = Settings(demo_mode=True, database_path=tmp_path / "support.db")
    store = CommerceStore(settings.database_path)
    store.seed_demo_orders(TEST_TODAY)
    policies = KnowledgeBase(settings.database_path)
    seed_policies(policies)
    deps = SupportDependencies(DemoLLM(), store, policies, settings, today=lambda: TEST_TODAY)
    return build_support_graph(deps, InMemorySaver()), store


def invoke(workflow, message: str, thread_id: str):
    return workflow.invoke(
        {"thread_id": thread_id, "message": message},
        config={"configurable": {"thread_id": thread_id}},
    )


def test_logistics_query_loads_real_order(tmp_path):
    workflow, _ = make_support_graph(tmp_path)
    result = invoke(workflow, "订单 EC2026002 的快递到哪了", "logistics-1")
    assert result["intent"].intent == "logistics"
    assert result["order"].tracking_no == "YT660092"
    assert result["decision"].action == "answer"
    assert "YT660092" in result["final_reply"]


def test_high_value_refund_requires_approval_and_executes(tmp_path):
    workflow, store = make_support_graph(tmp_path)
    result = invoke(workflow, "订单 EC2026001 不想要了，帮我退款", "refund-1")
    assert result["__interrupt__"]
    assert result["decision"].refund_amount == 299

    resumed = workflow.invoke(
        Command(resume={"approved": True}),
        config={"configurable": {"thread_id": "refund-1"}},
    )
    assert resumed["action_result"].success
    assert resumed["action_result"].reference_id.startswith("AS-")
    assert store.get_order("EC2026001").status == "refund_processing"


def test_rejected_refund_does_not_execute(tmp_path):
    workflow, store = make_support_graph(tmp_path)
    invoke(workflow, "订单 EC2026001 不想要了，帮我退款", "refund-reject")
    resumed = workflow.invoke(
        Command(resume={"approved": False}),
        config={"configurable": {"thread_id": "refund-reject"}},
    )
    assert "action_result" not in resumed
    assert store.get_order("EC2026001").status == "delivered"


def test_missing_order_id_asks_for_clarification(tmp_path):
    workflow, _ = make_support_graph(tmp_path)
    result = invoke(workflow, "我的快递到哪了", "missing-1")
    assert "请提供 EC 开头的订单号" in result["final_reply"]
    assert "decision" not in result


def test_expired_return_creates_manual_ticket(tmp_path):
    workflow, _ = make_support_graph(tmp_path)
    result = invoke(workflow, "订单 EC2026003 的椅子有损坏，我要退货退款", "expired-1")
    assert result["decision"].action == "create_ticket"
    assert result["action_result"].reference_id.startswith("AS-")
