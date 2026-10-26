模块名称：Agents

一、已实现能力
- Planner 输出结构化阶段、Mode、学习目标、前置知识、迁移任务和长期优先节点；Teaching Agent 依据不可变 Policy 决策生成教学回复；独立 Evaluator 检查答案泄露、支架、Mode、Policy、阶段、下一步和代写。工具调用有权限、Schema、超时、重试、降级与持久化 Trace。

二、核心新增/修改文件
- `backend/app/agents/{planner,teaching,evaluator,schemas,tool_runtime,tracing,prompts}.py`、`backend/app/core/{config,responses_provider}.py`、`backend/app/models/tool_trace.py`、`backend/migrations/versions/112be5269773_tool_trace.py`、`tests/test_module7_agents.py`、`scripts/demo_agents_live.py`、`docs/MODULE_07.md`、`README.md`。

三、核心接口
- `PlannerAgent.plan(...) -> PlannerPlan`；`TeachingAgent.generate(TeachingRequest) -> TeachingTurn`；`PedagogyEvaluator.evaluate(TeachingRequest, TeachingTurn) -> EvaluationResult`；`AgentToolRuntime.invoke(...)`；`configured_responses_provider(Settings)`。

四、执行的检查与测试
- 通用验收的代码质量、Schema/非法输入、正常/边界/重复/异常路径、真实 PostgreSQL 与前置服务联通、真实 DeepSeek 运行、架构边界、文档和前置回归；模块 7 Planner/Teaching/Evaluator 专项场景；Ruff format/check、mypy、pytest、Alembic 漂移检查。

五、测试结果
- 模块 7 测试 11/11，前置模块 1–6 回归 61/61，项目全量 72/72；Ruff、mypy、Alembic 均通过。真实样例输出 `kg_micro_lesson`，独立 Evaluator `pass`，数据库 Tool Trace 4 条，长期 Student State 前后一致。

六、发现并修复的问题
- DeepSeek 接入前缺少实际 Provider，已添加 Responses 适配器及其离线 wire-format 测试；测试文件 import 顺序不符合 Ruff，已修复；真实模型凭证配置后完成端到端验收。

七、已知限制
- 真实模型仅验收一个语法教学样例，输出质量会随模型响应变化；Evaluator 的 `BLOCK` 结果由模块 8 Workflow 接入自动重生成；真实调用需私有 DeepSeek Key。未运行 Benchmark，不声明模型效果指标。

八、回归结果
- 模块 1 的 17 项、模块 2 的 11 项、模块 3 的 7 项、模块 4 的 9 项、模块 5 的 8 项、模块 6 的 9 项全部通过。

九、是否满足本模块验收标准
是

十、是否具备进入下一模块的条件
是
