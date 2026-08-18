import re
from typing import Protocol, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr

from insightforge.config import Settings
from insightforge.domain import PlanStep, QualityReview, ResearchPlan
from insightforge.support.models import Intent, IntentResult, ResponseReview, ServiceDecision

T = TypeVar("T", bound=BaseModel)


class LLM(Protocol):
    def text(self, system: str, user: str) -> str: ...

    def structured(self, system: str, user: str, schema: type[T]) -> T: ...


class OpenAICompatibleLLM:
    """LangChain adapter for any OpenAI-compatible chat completion API."""

    def __init__(self, settings: Settings):
        self.model = ChatOpenAI(
            model=settings.llm_model,
            api_key=SecretStr(settings.llm_api_key.get_secret_value()),
            base_url=settings.llm_base_url,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
            max_retries=2,
        )

    @staticmethod
    def _messages(system: str, user: str) -> list[SystemMessage | HumanMessage]:
        return [SystemMessage(content=system), HumanMessage(content=user)]

    def text(self, system: str, user: str) -> str:
        result = self.model.invoke(self._messages(system, user))
        return str(result.content)

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        result = self.model.with_structured_output(schema).invoke(self._messages(system, user))
        if not isinstance(result, schema):
            return schema.model_validate(result)
        return result


class DemoLLM:
    """Free deterministic adapter: teaches the full graph without consuming tokens."""

    def text(self, system: str, user: str) -> str:
        if "最终" in system:
            return (
                "# 研究结论（Demo 模式）\n\n"
                "当前结论基于已导入的企业知识库证据。系统完成了规划、检索、分析、"
                "质量审查与报告生成；请关闭 `DEMO_MODE` 后使用真实模型获得针对性内容。\n\n"
                "## 核心发现\n\n"
                "- LangGraph 将 Agent 的步骤显式建模为可恢复的状态机。\n"
                "- 检索证据与生成过程解耦，便于替换为 pgvector 或 Elasticsearch。\n"
                "- Critic 节点以质量阈值控制反思循环，避免无限重试。\n\n"
                "## 风险与建议\n\n"
                "真实生产环境还应增加租户隔离、分布式限流和离线评测集。"
            )
        return (
            "## 分析草稿\n\n"
            "已综合当前证据形成初步判断。LangGraph 负责状态与路由，LangChain 负责模型抽象，"
            "检索层负责提供可追溯上下文。证据不足的结论应标记为待验证。"
        )

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        if schema is IntentResult:
            order_match = re.search(r"EC\d{7}", user.upper())
            if any(word in user for word in ("退款", "退货", "不要了")):
                intent = Intent.RETURN_REFUND
            elif any(word in user for word in ("物流", "快递", "到哪")):
                intent = Intent.LOGISTICS
            elif any(word in user for word in ("投诉", "差评", "生气")):
                intent = Intent.COMPLAINT
            elif any(word in user for word in ("订单", "状态")):
                intent = Intent.ORDER_STATUS
            else:
                intent = Intent.PRODUCT_HELP
            value = IntentResult(
                intent=intent,
                order_id=order_match.group(0) if order_match else None,
                needs_order=intent in {Intent.RETURN_REFUND, Intent.LOGISTICS, Intent.ORDER_STATUS},
                summary=user[-120:],
            )
            return schema.model_validate(value.model_dump())
        if schema is ServiceDecision:
            request_text = user.split("\n", 1)[0]
            amount_match = re.search(r'"amount":\s*([\d.]+)', user)
            amount = float(amount_match.group(1)) if amount_match else 0
            citations = list(dict.fromkeys(re.findall(r"KB-[a-f0-9]{8}", user)))[:3]
            if any(word in request_text for word in ("退款", "退货", "不要了")):
                value = ServiceDecision(
                    action="refund",
                    reason="用户提出退款，订单与政策信息已核验",
                    reply="已根据售后政策为你发起退款申请。",
                    refund_amount=amount,
                    risk_level="high" if amount > 200 else "low",
                    policy_citations=citations,
                )
            elif any(word in request_text for word in ("投诉", "损坏", "异常")):
                value = ServiceDecision(
                    action="create_ticket",
                    reason="需要人工售后进一步处理",
                    reply="我会创建售后工单并安排专人跟进。",
                    risk_level="medium",
                    policy_citations=citations,
                )
            else:
                value = ServiceDecision(
                    action="answer",
                    reason="可直接依据订单信息答复",
                    reply="订单信息已经查询完成。",
                    policy_citations=citations,
                )
            return schema.model_validate(value.model_dump())
        if schema is ResponseReview:
            value = ResponseReview(
                passed=True, policy_grounded=True, safe_to_execute=True, issues=[]
            )
            return schema.model_validate(value.model_dump())
        if schema is ResearchPlan:
            value = ResearchPlan(
                goal="形成有证据、可执行、可审计的研究报告",
                steps=[
                    PlanStep(
                        id="S1",
                        title="检索内部知识",
                        objective="查找与问题直接相关的企业资料",
                        search_query=user[:120],
                        needs_web=False,
                    ),
                    PlanStep(
                        id="S2",
                        title="补充外部事实",
                        objective="用公开资料交叉验证关键结论",
                        search_query=user[:120],
                        needs_web=True,
                    ),
                ],
                success_criteria=["回答核心问题", "区分事实与推断", "给出可执行建议"],
            )
            return schema.model_validate(value.model_dump())
        if schema is QualityReview:
            value = QualityReview(
                score=88,
                passed=True,
                strengths=["结构完整", "结论与证据分离"],
                issues=[],
                follow_up_queries=[],
            )
            return schema.model_validate(value.model_dump())
        raise ValueError(f"DemoLLM does not support schema: {schema.__name__}")


def build_llm(settings: Settings) -> LLM:
    return DemoLLM() if settings.demo_mode else OpenAICompatibleLLM(settings)
