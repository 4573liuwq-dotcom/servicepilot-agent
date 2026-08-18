from fastapi.testclient import TestClient

from insightforge.api import app


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_research_endpoint_in_demo_mode():
    with TestClient(app) as client:
        response = client.post(
            "/v1/research",
            json={"query": "解释 LangGraph 对企业 Agent 的价值", "require_approval": False},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["quality_score"] == 88
    assert body["report"]


def test_concrete_support_endpoint_queries_order():
    with TestClient(app) as client:
        response = client.post(
            "/v1/support/chat",
            json={"message": "帮我查询订单 EC2026002 的物流"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["intent"] == "logistics"
    assert body["order"]["tracking_no"] == "YT660092"
