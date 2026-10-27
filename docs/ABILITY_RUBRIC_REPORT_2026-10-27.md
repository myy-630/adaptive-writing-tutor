# 模块 8 补充验收：五维量表接入 Student State

模块名称：LangGraph Workflow 补充（联动模块 2、9）

一、已实现能力
- 审题、语法、结构、内容、句子表达分别从相应学生提交材料生成 0–1 过程性量表分；最终评估还对两稿中已识别语法模式生成一次语法分。评分不使用阶段通过/失败作为输入。`LearningEvidence.rubric_score` 触发现有五维 EMA，Student State Manager 的更新公式和 BKT 职责保持不变。缺少可评分材料时不造分。

二、核心新增/修改文件
- `backend/app/workflows/ability_rubric.py`、`stage_gate.py`、`store.py`；`tests/test_ability_rubric.py`、`tests/test_module8_workflow.py`；`frontend/src/components.tsx`、`scripts/demo_workflow_live.py`；`docs/ABILITY_RUBRIC.md`、模块 2/8/9 说明、README 和历史演示说明。

三、核心接口
- `ObservableWritingRubric.assess(...) -> RubricAssessment | None`；`StageGate.assess(...) -> StageOutcome` 中的 `rubric` 与 `evidence.rubric_score`；`workflow_events.stage_outcome.rubric` 保存版本及各项分值/权重；`StudentStateManager.record_evidence(...)` 沿用现有事务与 EMA。

四、执行的检查与测试
- 对照 `PROJECT_SPEC.md` 的通用验收和模块 2、8、9 专项验收；正常、空、非法、边界、重复、异常路径；八阶段真实 PostgreSQL 集成、失败阶段、独立模式、提交后中断恢复；全项目回归；真实 DeepSeek 工作流样例；Ruff、mypy、前端构建、Alembic 漂移检查和文档审查。

五、测试结果
- 后端全量 `103 passed`；前端 `29 passed`；Ruff、mypy（71 个源码文件）、前端 TypeScript/Vite 构建、Alembic `check` 均通过。八阶段数据库样例保存 6 条有量表分的事件，五维能力证据数为审题 1、语法 2、结构 1、内容 1、句子表达 1；逐条按 EMA 公式核对数据库状态。真实 DeepSeek 审题样例：量表分 1.00，审题能力由 0.50 更新至 0.65，4 条 Tool Trace，Evaluator `pass`，下一阶段为初稿。
- 本地浏览器重新创建一条示例会话并提交审题后，工作区在初稿阶段显示“审题 65%”及“依据 1 条过程性量表证据更新”；[实测截图](assets/ability-rubric-live-2026-10-27.jpg)。

六、发现并修复的问题
- 原工作流学习证据缺少 `rubric_score`，导致五维 EMA 实际不触发；现由独立评分程序填入。缺失任务要点、计划或原稿语法错误时取消对应评分项并重分配权重，避免凭缺失信息得满分。新增已提交阶段结果的重放测试，确认中断后补写证据且重复请求不重复计分。一个测试样例的内容分恰好等于初始 0.50，改为直接验证 EMA 公式和证据数，不把数值相等误判为未更新。

七、已知限制
- 量表评估可观察写作特征，不代表作文整体质量或教学成效。词面匹配、词数和连接词会漏掉同义表达，也可能被机械堆砌；语法评分仅覆盖当前 Analyzer 的规则。历史无分数证据没有自动回填。未引入新 Benchmark 指标或外部评分数据。

八、回归结果
- 模块 1–10 现有重要后端测试和模块 9 前端测试全部通过；阶段顺序、Planner/Policy/Teaching/Evaluator 职责、KG/RAG 分离、独立模式权限、证据幂等和数据库迁移均未改变。

九、是否满足本模块验收标准
是。

十、是否具备进入下一模块的条件
是。本次为已完成模块的缺口修复，项目模块 1–10 已完成。
