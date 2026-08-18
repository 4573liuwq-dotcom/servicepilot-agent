# Contributing

欢迎提交小而清晰的 Pull Request。开始前请创建 Issue 描述场景和验收标准；代码需通过：

```bash
ruff check .
ruff format --check .
pytest
```

新增 Agent 节点时，请说明它为什么不能由现有节点承担、失败如何降级、成本如何终止，并至少增加一个不调用真实 API 的测试。
