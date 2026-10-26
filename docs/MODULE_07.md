# 模块 7：Agents

已接入三个明确分工的组件：`PlannerAgent` 输出阶段、Mode、当前能力目标、长期弱项、KG prerequisite 和迁移作文题的结构化计划；`TeachingAgent` 接收不可变的 Policy 决策，用 Student State 和按权限检索的 RAG 材料生成回复；`PedagogyEvaluator` 独立检查答案泄露、支架强弱、Mode/Policy、阶段、可执行下一步和代写风险。独立模式的 Teaching Agent 不调用模型或工具，也不生成教学回复。

`AgentToolRuntime` 用 Pydantic 参数校验、Actor allowlist、超时、重试、降级和 PostgreSQL `tool_call_records` 审计记录包裹 State/KG/RAG 只读工具。长期 Student State 仍只由 `StudentStateManager` 修改。实际 KG prerequisite、RAG 教材、迁移作文题和持久化 Tool Trace 已与真实 PostgreSQL 测试数据联通。

模型接口采用 `ModelProvider`，默认接入 DeepSeek。根据 [DeepSeek 官方文档](https://api-docs.deepseek.com/api/create-response/)，其 Responses API 支持 `json_schema` 输出；项目使用 OpenAI SDK 的 `responses.parse(..., text_format=...)` 与本地 Pydantic 二次验证。适配器设置 `store=False`，Key 从 `DEEPSEEK_API_KEY` 环境变量或私有 `.env` 读取，默认模型 `deepseek-flash`。运行 `.venv/bin/python scripts/demo_agents_live.py` 需要可用的 DeepSeek Key 和模型权限。保留 `MODEL_PROVIDER=openai` 作为可替换 Provider 的开发选项，不影响默认产品接入。

完成了合同、权限、错误处理、真实本地服务集成测试，以及通过本地 HTTP Transport 对 DeepSeek `/responses` 请求的序列化验证（`json_schema`、`store=False`）。真实模型样例使用初三学生的主谓一致重复错误：Planner 保留语法修改阶段，选择 `subject_verb_agreement` 目标和 `subject_predicate` 前置知识；Policy 决定 `kg_micro_lesson` 且禁止直接揭示目标句答案；Teaching Agent 生成规则解释、学生原句自改提示和迁移练习；独立 Evaluator 返回 `pass`；PostgreSQL 留下 4 条 Tool Trace；Agent 运行前后长期 Student State 一致。

验收执行：模块 7 测试 11/11、模块 1–6 回归 61/61、项目全量 72/72，Ruff、mypy 和 Alembic 漂移检查均通过。完整结论见 `docs/MODULE_07_REPORT.md`。

已知限制：模型输出存在随机性，真实样例只验证一条语法教学路径；工具权限与严重违规阻断已实现，自动重生成将在模块 8 Workflow 中接通；DeepSeek 真实调用需要私有 API Key。DeepSeek 是模型输出来源，KG 种子和项目演示资源由本项目维护，RAG 的公开例句来源与许可见模块 4 文档。
