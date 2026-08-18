# 通过电商售后项目读懂 Agent、LangChain 与 LangGraph

## 先建立三个概念

**Agent** 不是某个库，而是“模型根据状态选择动作、使用工具、观察结果并继续决策”的系统模式。在 ServicePilot 中，订单数据库、政策检索、退款与工单都是工具；模型理解诉求，代码约束并执行动作。

**LangChain** 在本项目主要承担模型适配和结构化输出。`OpenAICompatibleLLM` 隔离了具体 provider，让业务节点不关心请求格式。

**LangGraph** 承担控制流。你可以把它理解成专门为长时间、带状态的 AI 任务设计的状态机：State 是白板，Node 是团队成员，Edge 是交接规则，Checkpointer 是存档。

## 先跟一次售后请求走完整图

主代码是 `src/insightforge/support/graph.py`：

1. `guardrail`：阻止明显提示词注入和超长输入。
2. `understand`：生成结构化 `IntentResult`，提取意图与订单号。
3. `load_order`：调用订单工具；缺订单号时直接追问，不让模型猜。
4. `retrieve_policy`：根据诉求检索退换货、物流和风控政策。
5. `decide`：生成 `ServiceDecision`，代码再次校验金额与七天期限。
6. `review`：独立风控 Agent 判断操作是否安全、有政策依据。
7. `approval`：高金额退款调用 `interrupt()`；主管通过同一 thread 恢复。
8. `execute`：创建退款或工单，使用幂等键并写审计日志。
9. `respond`：把订单、处理结果、流水号和政策依据返回用户。

通用研究工作流仍保留在 `src/insightforge/agents/graph.py`，适合学完具体应用后比较两种图的差异。

## 原有研究图的节点（进阶对比）

1. `guardrail`：在调用模型前检查输入边界。
2. `planner`：使用 `ResearchPlan` 强制模型返回明确步骤，而非不可解析的自然语言。
3. `approval`：需要时调用 `interrupt()` 暂停；同一 `thread_id` 用 `Command(resume=...)` 恢复。
4. `researcher`：执行知识库与网络检索。外部搜索失败不会让全任务失败。
5. `analyst`：证据约束生成，要求用 ID 引用。
6. `critic`：返回 `QualityReview`。条件边决定回到 Researcher 还是进入 Finalizer。
7. `finalizer`：综合证据和审计意见输出最终报告。

建议在 `graph.py` 每个节点第一行打断点，观察 `state` 如何逐步增加字段。

## 为什么结构化输出重要

若 Planner 返回一段散文，代码无法可靠知道有多少步骤、哪个步骤需要联网。Pydantic 模型把模型输出变成运行时契约：字段缺失或类型错误会直接暴露，而不是悄悄污染后续节点。

## RAG 在哪里

`KnowledgeBase.ingest_text` 将长文切成重叠分块并持久化；`search` 只返回相关片段；Analyst 看到的不是整个数据库，而是一次查询的证据集合。这就是 Retrieval-Augmented Generation 的最小闭环。

当前排序是可解释的关键词匹配。升级为混合检索时，不改 Agent 节点，只替换 `KnowledgeBase.search`：

```text
query → BM25 候选 + vector 候选 → RRF 融合 → reranker → top-k evidence
```

## 二次开发任务

按难度逐步做，并给每项补测试：

1. 入门：在最终结果中返回每个节点的 `events` 时间线。
2. 入门：给知识文档增加 `department` 和 `effective_date` 元数据过滤。
3. 进阶：接入 pgvector 与 embedding，做关键词/向量混合检索。
4. 进阶：加入 LangSmith 或 OpenTelemetry，记录节点延迟和 token 成本。
5. 高阶：建立 30 条业务问题评测集，衡量引用正确率、答案完整率和平均成本。
6. 高阶：实现多租户 RBAC，让不同部门只能检索自己的知识。

完成第 3、5 项后，这个项目才真正成为“你的项目”，也会产生可量化的简历指标。

## 常见误区

- 节点越多不代表越智能；每个节点应有独立职责或失败策略。
- “有 RAG”不等于事实可靠；必须评估检索召回和引用是否支持结论。
- 反思不应无限循环；它必须受成本、时间和最大轮数约束。
- Demo 跑通不是生产可用；持久 checkpointer、权限、评测和监控不能省略。
