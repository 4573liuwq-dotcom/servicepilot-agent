"""Run reproducible ServicePilot scenarios without starting an HTTP server."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from insightforge.api import app, commerce_store


def show(title: str, payload: dict) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    commerce_store.reset_demo()
    with TestClient(app) as client:
        logistics = client.post(
            "/v1/support/chat",
            json={"message": "帮我查询订单 EC2026002 的物流"},
        )
        logistics.raise_for_status()
        show("场景一：物流查询", logistics.json())

        refund = client.post(
            "/v1/support/chat",
            json={"message": "订单 EC2026001 不想要了，帮我退款"},
        )
        refund.raise_for_status()
        refund_body = refund.json()
        show("场景二：高金额退款暂停审批", refund_body)
        if refund_body["status"] != "needs_approval":
            raise RuntimeError("高金额退款没有进入审批，请检查演示订单日期与风险规则")

        approved = client.post(
            f"/v1/support/{refund_body['thread_id']}/resume",
            json={"approved": True, "feedback": "演示：主管核验通过"},
        )
        approved.raise_for_status()
        approved_body = approved.json()
        show("场景三：审批恢复并执行", approved_body)

        repeated_response = client.post(
            "/v1/support/chat",
            json={
                "message": "订单 EC2026001 不想要了，帮我退款",
                "thread_id": refund_body["thread_id"],
            },
        )
        repeated_response.raise_for_status()
        repeated = repeated_response.json()
        first_reference = approved_body["action_result"]["reference_id"]
        repeat_reference = repeated["action_result"]["reference_id"]
        show(
            "场景四：重复退款被幂等拦截",
            {
                "first_reference_id": first_reference,
                "repeat_reference_id": repeat_reference,
                "same_reference": first_reference == repeat_reference,
                "message": repeated["action_result"]["message"],
            },
        )

        actions = client.get("/v1/support/actions")
        actions.raise_for_status()
        action_rows = actions.json()
        show(
            "业务流水与幂等记录",
            {"action_count": len(action_rows), "actions": action_rows},
        )


if __name__ == "__main__":
    main()
