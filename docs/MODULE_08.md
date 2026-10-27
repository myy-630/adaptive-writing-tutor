# 模块 8：LangGraph Workflow

## 工作流与职责

`WritingWorkflow` 用 LangGraph 编排 `load → apply_response → Planner → diagnose → Policy → Teaching → Evaluator → finish`。Evaluator 返回 `BLOCK` 或 `DIRECTIVE` 时，最多重生成 `WORKFLOW_MAX_REGENERATIONS` 次；到达上限后结果标记 `blocked`，教学文本不返回。完整作文按照审题、初稿、语法修改、结构修改、内容补充、语言优化、二次重写、最终评估八个固定阶段推进。Planner 可在首次语法诊断后将新发现的知识点纳入结构化计划；Policy 仍独立决定教学动作，Teaching Agent 只表达决策。

`SharedState` 包含请求与会话身份、提交内容、当前 Stage/Mode、题目与 Draft、Planner 计划、诊断、Policy 上下文和决策、教学回复、独立评价、重试次数、阶段结果和最终输出。LangGraph 只决定节点与路由；阶段门槛在 `StageGate`，草稿比较在 `draft_comparison`，学习证据由 `StudentStateManager` 事务化写入，事件与草稿由 `WorkflowStore` 持久化。Tool Runtime 处理工具权限、超时、重试、降级和 Trace。

HTTP 层从 FastAPI lifespan 取得进程内只读检索快照及模型 Provider，索引版本变化时替换完整检索快照；Student State Manager 仍按请求读取数据库，不复用学生状态或模型回复。检索结果缓存目前没有启用，原因与实测见 [模块 4 说明](MODULE_04.md)。

进入最终评估阶段时，Draft 2 已保存，工作流直接结束该次提交；页面下一步只有 `finalize`，因此不会再生成要求学生提交新稿的教学话术。`finalize` 由 `StageGate` 计算两稿对比与学习证据。Pedagogy Evaluator 同时会拦截在二次重写之前把当前草稿误称为已完成 Draft 2 的回复。

## 阶段门槛

- 审题：完整填写写作对象、目的、文体、要点、时态、人称和约束；文体与任务一致，任务要求的要点均被覆盖。
- 独立模式审题：学生用自由文本说明文体和必写要点；不要求填写结构化审题表。
- 初稿：提交不少于 `WORKFLOW_MIN_DRAFT_WORDS` 的学生文本。
- 语法修改：提交修订稿，已识别的语法问题消失；如上轮 Policy 要求迁移练习，必须答对固定、可核对的迁移题。
- 结构修改：提交开头、主体、结尾规划和修订稿。
- 内容补充：提交观点、原因、例子、细节、结果或感受，并修改自己的稿件。
- 语言优化：解释句间关系，并修改自己的表达。
- 独立模式结构、内容和语言阶段只要求学生修改自己的文本，不暴露引导表单。
- 二次重写：学生确认独立完成且提交与 Draft 1 不同的 Draft 2；系统不提供完整 AI 修改稿。
- 最终评估：比较 Draft 1 与 Draft 2 中分析器识别的错误类型，区分已消失、仍出现和新出现的模式；生成学习反馈和结构化证据。

这些门槛是可测试的早期规则，不能视为作文质量分数。语法分析器只识别当前实现的保守规则；未识别错误不会被此门槛检测。固定迁移题覆盖当前五类诊断知识节点；不支持的节点不能被虚假标记为迁移成功。

## 五维能力量表与证据

阶段门槛之后由独立的 `ObservableWritingRubric` 对学生提交材料评分，评分函数不接收阶段通过/失败结果。审题、语法修改、结构修改、内容补充、语言优化分别形成对应维度的 0–1 过程性量表分；最终评估还会根据 Draft 1/Draft 2 中识别的语法模式形成一次语法分。初稿和二次重写仍记录学习证据，但没有可用的本量表分数。`StageGate` 把评分写进 `LearningEvidence.rubric_score`，`StudentStateManager` 继续负责事务化 EMA；评分版本与各项明细保存在 `workflow_events.stage_outcome.rubric`，重复请求不会重复计分。各维标准、缺失项处理及解释边界见 [五维写作能力的过程性量表](ABILITY_RUBRIC.md)。

## 持久化、恢复与请求去重

依赖实现参照 [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api) 与 [持久化文档](https://docs.langchain.com/oss/python/langgraph/persistence)。

LangGraph 的 PostgreSQL checkpoint 以 `request_id` 为 thread ID，节点完成时同步保存；其四张 checkpoint 表由 LangGraph 自行管理，Alembic 只管理应用表。`workflow_events` 保存原始请求、阶段结果、Policy 决策和最终输出。相同 `request_id` 的重复请求返回原结果；并发执行同一请求由 PostgreSQL advisory lock 拒绝第二个执行。阶段、草稿和事件标记在应用事务中写入；学习证据使用由请求 ID 派生的稳定 ID 幂等补写。模型调用中断后用相同请求 ID 可从 checkpoint 继续，且不会重复推进阶段或重复计入证据。

## HTTP 接口

- `POST /students`、`GET /students/{student_id}/state`：学生与长期状态。
- `POST /tasks`：保存题目和必答要点。
- `POST /sessions`：建立阶段化教学会话。
- `GET /sessions/{session_id}?student_id=...`：返回题目、Stage、Mode、当前学生草稿、Student State、上一轮结果及语法阶段的错误定位和知识路径，供工作区恢复。定位数据只含原始片段、范围、类别和知识节点，不含修改答案；独立模式不返回上一轮教学结果或语法辅助数据。
- `POST /sessions/{session_id}/turn`：提交 `WorkflowTurnInput`，返回结构化 `WorkflowResult`；错误请求使用明确状态码。

运行 `scripts/demo_workflow_live.py` 可验证真实 DeepSeek 起始轮、审题提交及量表分进入 Student State。模块 8 的数据库集成测试另覆盖八阶段完整作文、中断恢复、独立模式、工具降级、重生成上限和幂等。HTTP 目前以调用者提供的学生 UUID 检查会话归属；项目尚无账号登录和生产级身份认证。模型输出会变化，最终评价只陈述分析器识别的模式变化；过程性量表也不宣称完整写作质量评分或 Benchmark 效果。知识图谱、公开例句和项目演示资源来源分别见模块 3、4 文档；DeepSeek 是在线教学表达和开放式教学评价的外部模型服务。
