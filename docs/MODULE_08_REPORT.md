模块名称：LangGraph Workflow

一、已实现能力
- 八阶段作文工作流、结构化 Shared State、Planner/Analyzer/Policy/Teaching/Evaluator 编排、拒绝后有界重生成、学生响应后学习证据更新、PostgreSQL checkpoint 恢复、请求去重、工具降级、Draft 1/2 规则对比与工作流 HTTP 接口。

二、核心新增/修改文件
- `backend/app/workflows/{graph,schemas,stage_gate,store,draft_comparison}.py`、`backend/app/api/workflow.py`、`backend/app/services/{grammar/transfer,pedagogy/intent}.py`、`backend/app/models/workflow.py`、模块 8 迁移、`tests/test_module8_workflow.py`、`scripts/demo_workflow_live.py`、`docs/MODULE_08.md`、`README.md`。

三、核心接口
- `WritingWorkflow.run(...) -> WorkflowResult`、`StageGate.assess(...) -> StageOutcome`、`WorkflowStore.register/apply/complete`、`compare_drafts(...)`、`POST /sessions/{id}/turn`、`GET /sessions/{id}`。

四、执行的检查与测试
- 通用代码质量、Schema、单元/集成/真实样例、职责边界、回归及文档检查；模块 8 十四项专项要求；Ruff、mypy、pytest、Alembic 漂移检查；真实 DeepSeek HTTP → LangGraph 样例。

五、测试结果
- 模块 8 专项 10/10，模块 1–7 回归 72/72，项目全量 82/82；Ruff、mypy、Alembic 均通过。真实 DeepSeek 起始轮：`prompt_analysis`、`guided`、Evaluator `pass`、2 条 Tool Trace，起始轮长期 Student State 前后一致。

六、发现并修复的问题
- 阶段事务持有会话行锁时写学习证据会等待外键锁；改为阶段事务先提交，再按稳定证据 ID 幂等补写。排除 LangGraph 自管理表以避免 Alembic 误判删除。首次语法错误无历史知识状态时，由 Planner 在诊断后补充具体目标。迁移练习由可核对题目判定，避免任意回答被记为成功。

七、已知限制
- 阶段通过门槛为可测试规则，不能替代人工或全面作文质量评估；语法分析器覆盖范围有限。真实模型只运行一条起始轮样例；八阶段完整流程用脚本化 Provider 与真实数据库验证。HTTP 尚无账号登录或生产级身份认证；固定迁移题只覆盖当前诊断节点。不声明 Benchmark 指标。

八、回归结果
- 模块 1–7 的 72 项测试全部通过；模块 7 的 Planner、Teaching、Evaluator 和工具权限回归通过。

九、是否满足本模块验收标准
是

十、是否具备进入下一模块的条件
是
