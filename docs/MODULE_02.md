# 模块 2：Student State

## 能力与职责

`StudentStateManager` 是普通服务，不是聊天 Agent。它在 PostgreSQL 事务中初始化学生状态、写入学习证据、更新知识/能力状态、记录错误事件，并向 Planner 与 Policy 提供同一个只读接口 `StudentStateReader.read_student_state(student_id)`。

## 核心接口

- `initialize_student(student)`：幂等初始化或补全从模块 1 迁移来的学生；同 ID 不同画像报冲突。
- `record_evidence(evidence) -> bool`：证据 ID 唯一；第一次提交返回 `True`，完全相同的重复提交返回 `False`，同 ID 不同内容报冲突。
- `record_error(error) -> bool`：错误事件按 ID 去重。
- `error_counts(student_id, start, end)`：按 `[start, end)` 半开时间窗口聚合错误类别和知识点。
- `read_student_state(student_id)`：返回画像、五维能力、知识状态、错误模式、提示依赖与当前交互状态。
- `set_current_session`、`set_confusion_score`：供后续 Workflow 与意图识别更新当前交互状态；均校验会话归属。

## 更新公式与配置

- 离散知识点：标准 BKT 观察后验，再应用学习转移。`BKT_INITIAL_MASTERY`、`BKT_LEARN`、`BKT_GUESS`、`BKT_SLIP` 可由环境变量配置。只用明确成功/失败更新 mastery；`uncertain` 保留记录但不增加判定性证据计数。
- 开放写作能力：`new = ABILITY_EMA_ALPHA × rubric_score + (1 − ABILITY_EMA_ALPHA) × old`。仅带有效 Rubric Score 的证据更新该维度。
- Workflow 的 `ObservableWritingRubric` 在对应阶段根据学生提交材料产生 0–1 分；评分标准与适用范围见 [五维写作能力的过程性量表](ABILITY_RUBRIC.md)。本模块只验证分数并执行 EMA，不负责评分。
- confidence：`decisive_evidence_count / (decisive_evidence_count + CONFIDENCE_PRIOR_WEIGHT)`。
- 平均提示等级：所有已提交学习证据的 `hint_level` 总和除以证据数；`0` 代表独立完成。

## 持久化与约束

迁移 `4d651e0f3d24_student_state` 增加 `student_states`、`ability_states`、`knowledge_states`、`learning_evidence`、`error_events`，并为学生画像增加 `preferences`。唯一证据 ID 在数据库层约束；冲突插入使用 PostgreSQL `INSERT ... ON CONFLICT DO NOTHING RETURNING`，只有真实插入才触发状态更新。会话与学生归属在写入前验证。

## 已知限制

Student State 的 UI 展示和 Planner 决策已由后续模块实现；意图语义分析仍只覆盖现有功能。错误事件由上游 Analyzer/Workflow 生成，本模块只负责校验、持久化与聚合。状态更新依照提交顺序处理；历史无量表分的证据不自动回填，若需回填必须按时间顺序提交可核对的评分结果。

## 外部依赖与数据来源

仅使用现有 PostgreSQL 实例，无外部教学数据或 API Key。测试样本为项目内自造样例，没有 Benchmark 指标。
