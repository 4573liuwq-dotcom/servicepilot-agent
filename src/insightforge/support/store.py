import json
import sqlite3
import uuid
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from insightforge.support.models import ActionResult, Order


class CommerceStore:
    """SQLite-backed demo order system with auditable, idempotent actions."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY, customer_name TEXT NOT NULL,
                    product_name TEXT NOT NULL, amount REAL NOT NULL, status TEXT NOT NULL,
                    paid_at TEXT NOT NULL, delivered_at TEXT, tracking_no TEXT
                );
                CREATE TABLE IF NOT EXISTS service_actions (
                    id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
                    order_id TEXT, action TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL,
                    event TEXT NOT NULL, detail TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            connection.commit()

    def seed_demo_orders(self, today: date | None = None) -> None:
        """Seed fictional orders with dates relative to the demo day.

        Relative dates keep the approval and expired-return scenarios reproducible
        instead of silently changing behavior as fixed calendar dates age.
        """
        current_day = today or date.today()
        rows = [
            (
                "EC2026001",
                "林晓",
                "AirBuds Pro 无线耳机",
                299.0,
                "delivered",
                (current_day - timedelta(days=5)).isoformat(),
                (current_day - timedelta(days=3)).isoformat(),
                "SF138001",
            ),
            (
                "EC2026002",
                "周晨",
                "智能恒温水杯",
                89.0,
                "in_transit",
                (current_day - timedelta(days=2)).isoformat(),
                None,
                "YT660092",
            ),
            (
                "EC2026003",
                "陈一",
                "人体工学办公椅",
                1299.0,
                "delivered",
                (current_day - timedelta(days=35)).isoformat(),
                (current_day - timedelta(days=30)).isoformat(),
                "JDVA7701",
            ),
        ]
        with closing(self._connect()) as connection:
            connection.executemany(
                """INSERT OR IGNORE INTO orders
                (order_id, customer_name, product_name, amount, status,
                 paid_at, delivered_at, tracking_no)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            connection.commit()

    def get_order(self, order_id: str) -> Order | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM orders WHERE order_id = ?", (order_id.upper(),)
            ).fetchone()
        return Order.model_validate(dict(row)) if row else None

    def execute(
        self, *, thread_id: str, order: Order | None, action: str, amount: float, reason: str
    ) -> ActionResult:
        order_id = order.order_id if order else None
        key = f"{thread_id}:{action}"
        with closing(self._connect()) as connection:
            existing = connection.execute(
                "SELECT * FROM service_actions WHERE idempotency_key = ?", (key,)
            ).fetchone()
            if existing:
                return ActionResult(
                    action=action,
                    success=existing["status"] == "success",
                    reference_id=existing["id"],
                    message="幂等命中：该操作已经执行，无需重复提交。",
                )
            reference = f"AS-{uuid.uuid4().hex[:8].upper()}"
            payload = json.dumps({"amount": amount, "reason": reason}, ensure_ascii=False)
            connection.execute(
                """INSERT INTO service_actions
                (id, idempotency_key, order_id, action, payload, status)
                VALUES (?, ?, ?, ?, ?, 'success')""",
                (reference, key, order_id, action, payload),
            )
            connection.execute(
                "INSERT INTO audit_logs(thread_id, event, detail) VALUES (?, ?, ?)",
                (thread_id, f"action:{action}", payload),
            )
            if action == "refund" and order_id:
                connection.execute(
                    "UPDATE orders SET status = 'refund_processing' WHERE order_id = ?", (order_id,)
                )
            connection.commit()
        message = (
            "退款申请已提交，预计 1-3 个工作日原路退回。"
            if action == "refund"
            else "售后工单已创建，客服将在 2 小时内跟进。"
        )
        return ActionResult(action=action, success=True, reference_id=reference, message=message)

    def list_actions(self, limit: int = 20) -> list[dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM service_actions ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def reset_demo(self) -> None:
        """Reset only the bundled fictional commerce data."""
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM service_actions")
            connection.execute("DELETE FROM audit_logs")
            connection.execute("DELETE FROM orders")
            connection.commit()
        self.seed_demo_orders()
