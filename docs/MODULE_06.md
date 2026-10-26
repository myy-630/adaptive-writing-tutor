# 模块 6：Pedagogy Policy

## 职责与接口

`PedagogyPolicy.decide(context: PolicyContext) -> TeachingDecision` 只决定当前问题**怎样教**。Planner 将在后续模块决定学习目标、阶段与 Mode；Teaching Agent 将根据决策生成具体话术。Policy 不生成学生回复、不修改 Student State、不调用 LLM，也不改变 Planner 的目标或 Mode。

`PolicyContext` 包含规范要求的阶段、问题类型、目标知识点、mastery 与 confidence、历史/最近错误、上次动作及成败、Mode、学生意图、连续失败、提示依赖、困惑与挫败。`PolicyContext.from_student_state` 从统一 `StudentStateSnapshot` 读取已有指标，其余瞬时输入由上层传入。没有该知识点历史记录时，使用中性 mastery 0.5 和 confidence 0，避免凭空宣称已掌握。

`allowed_actions` 先执行 Stage 与 Mode 的硬约束，再过滤无图谱目标的微课、尚未满足条件的迁移练习和直接讲解。独立模式仅允许 `independent_retry`，不开放提示。直接讲解须同时满足：至少连续失败三次、上次较强支架动作失败、当前不是独立模式。学生要求“直接告诉我”本身不能触发讲解。之后采用确定性的规则与启发式评分，按分数和动作名称稳定排序；每项 `ActionScore` 保留原因。`TeachingDecision` 给出动作、目标知识点、支架等级、答案权限、练习、通过条件、失败后动作、理由和完整 Ranking。

## 实际数据流

```text
Grammar Analyzer 的内部诊断 + Student State Snapshot + 当前 Stage/Mode/Intent
→ PolicyContext → Stage/Mode 过滤 → 启发式 Ranking → TeachingDecision
```

运行 `.venv/bin/python scripts/demo_pedagogy_policy.py` 可在本地测试数据库中创建样例学生和会话，记录两次真实错误与失败证据，读取状态和图谱诊断，再输出结构化决策。此演示会写入测试数据库。模块专项测试同时覆盖独立模式、直接请求、强引导、重复错误、支架升级、不同 Stage、非法/边界输入、重复调用和序列化。

## 已知限制

当前评分是可解释的规则与启发式，不是强化学习、Learning-to-Rank 或 Contextual Bandit，也没有真实教学效果指标。`on_failure` 是建议动作，下一轮仍需重新运行 Policy 以考虑新的学生证据与 Mode。意图标签与最近错误复现由后续 Workflow 提供；模块 6 不自行做对话意图识别。微课的目标 ID 由上游已验证的 Grammar Analyzer / KG 链接提供。

## 外部依赖与数据来源

复用模块 1–5 的 Pydantic、PostgreSQL Student State、Grammar Analyzer 和项目内 Grammar Knowledge Graph；不需要新的外部服务、API Key 或数据源。
