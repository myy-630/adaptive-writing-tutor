模块名称：Pedagogy Policy

一、已实现能力
- Stage/Mode 硬过滤、十一种候选动作的确定性评分与解释性 Ranking、按 mastery/confidence/失败/重复错误选择支架、直接讲解门槛、完整结构化决策。

二、核心新增/修改文件
- `backend/app/services/pedagogy/{schemas,policy}.py`、`backend/app/domain/schemas.py`、`tests/test_module6_pedagogy_policy.py`、`scripts/demo_pedagogy_policy.py`、`docs/MODULE_06.md`、`README.md`。

三、核心接口
- `PolicyContext.from_student_state(...)`、`PedagogyPolicy.allowed_actions(context)`、`PedagogyPolicy.decide(context) -> TeachingDecision`；`StudentIntent`、`ActionScore`。

四、执行的检查与测试
- 模块 6 十四项专项验收场景；真实 PostgreSQL 学生状态、KG 和 Analyzer 联通；实际演示；Pydantic 非法/空/边界、重复调用与异常路径；Ruff、mypy、Alembic 漂移、Prompt/Agent 越界检查、模块 1–5 全量回归。

五、测试结果
- 模块 6 专项 9/9，通过；模块 1–5 回归 52/52，通过；全量 61/61，通过。真实样例两次 `subject_verb_agreement` 错误与两次失败证据，决策 `kg_micro_lesson`、支架等级 3、禁止直接开放答案。Alembic 无新升级操作。

六、发现并修复的问题
- 集成测试曾误用诊断对象的 `category` 字段，改为实际 `primary_category` 后通过；将 mastery confidence 纳入轻支架判定，避免低置信度时仅凭高 mastery 触发自查优先。

七、已知限制
- 评分是启发式而非学习策略或已验证效果；瞬时意图及最近错误复现需上层提供；失败后建议动作须在下一轮重新决策。

八、回归结果
- 模块 1 的 17 项、模块 2 的 11 项、模块 3 的 7 项、模块 4 的 9 项、模块 5 的 8 项重要测试全部通过。

九、是否满足本模块验收标准
是

十、是否具备进入下一模块的条件
是
