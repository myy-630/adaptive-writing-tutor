# 模块 5：Grammar Analyzer

## 职责与接口

`GrammarAnalyzer.analyze(text) -> GrammarAnalysis` 只负责内部诊断，不选择教学动作、不更新 Student State、不生成对学生的教学回复。它将句子、段落或作文拆分为句子，输出稳定排序的错误列表。每个 `GrammarError` 包含全局字符位置、原始/正确表达、原句/修改后完整句子、一级类别、细分错误类型、原句和正确句结构、结构变化、原因、置信度、严重程度与对应 KG 节点 ID。

识别规则目前涵盖：明确过去时间标志词下的常见动词时态、常见主谓一致、限定词缺失或 `a/an` 选择、从属句残缺，以及有限模式的句子粘连。图谱映射通过 `GrammarKnowledgeGraph.link_error` 完成；若规则对应的图谱节点缺失，服务明确失败，避免无链接诊断。无把握或未覆盖的表达不会强行报错。

## 集成与数据流

```text
学生文本 → Grammar Analyzer → 结构化内部诊断 → 后续 Pedagogy Policy / Teaching Agent
```

学生 API 目前没有原始诊断端点。后续 Workflow 只能通过教学决策和 Teaching Agent 选择如何呈现提示；原始纠正内容不直接显示到学生工作区。

## 已知限制

当前是可测试的保守规则诊断，不是通用英语语法检查器。词汇与句型覆盖有限，复杂从句、语境依赖、语义错误可能漏检；句子结构标签为启发式结果。低置信度代表规则存在歧义，不能当作确定事实。下一阶段的 Pedagogy Policy 仍须独立决定怎样教。

## 外部依赖与来源

复用 PostgreSQL 中的项目内语法图谱，不需新外部数据、API Key 或模型下载；没有 Benchmark 效果数据。
