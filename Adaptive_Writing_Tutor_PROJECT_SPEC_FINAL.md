# Adaptive Writing Tutor — 项目总说明与模块验收规范

> 面向初高中英语写作的状态化、自适应教学 Agent 系统<br>
> 本文档是项目开发过程中的最高设计约束与验收规范。<br>
> 所有模块必须遵守本文档，不得擅自改变核心架构、职责边界和教学逻辑。

---

# 1. 项目定位

本项目不是普通的作文批改器、范文生成器或聊天机器人。

目标是构建一个能够长期维护学生状态，并根据学生当前能力、历史错误、提示依赖和实时表现，自适应决定：

1. 下一步学什么；
2. 当前处于哪个教学阶段；
3. 应采用多强的教学支架；
4. 当前应该使用什么教学动作；
5. 是否允许直接给答案；
6. 是否需要插入微课、练习或迁移任务；
7. 学生完成本轮学习后，如何更新长期 Student State。

核心闭环：

```text
学生长期状态
↓
学习规划
↓
阶段化教学 Workflow
↓
教学策略选择
↓
学生尝试
↓
教学质量评估
↓
学习证据
↓
学生状态更新
↓
下一步规划
```

---

# 2. 核心架构原则

## 2.1 大流程稳定，小流程自适应

作文教学主流程固定为：

```text
审题
→ 初稿
→ 语法自查与修改
→ 结构修改
→ 内容补充
→ 语言优化
→ 二次重写
→ 最终评估
```

宏观流程原则上不由 LLM 自由改变。

每个阶段内部采用的教学动作、支架等级、是否插入微课、是否允许示范等，可以根据 Student State 动态变化。

## 2.2 规划、策略、表达、评估必须解耦

- Planner Agent：决定“学什么、下一步去哪、是否切换模式”。
- Pedagogy Policy：决定“当前应该怎么教”。
- Teaching Agent：决定“具体怎么说”。
- Pedagogy Evaluator：检查“这一轮有没有教错”。
- Student State Manager：维护结构化状态，不作为聊天 Agent。
- Grammar Analyzer：负责诊断错误，不负责教学决策。
- Knowledge Graph：负责知识结构与关系。
- Retrieval System：负责检索教学资源。

禁止把这些职责塞入单一 Agent 或单一 Prompt。

## 2.3 确定性逻辑优先使用普通代码

以下逻辑应优先由普通代码实现：

- 数据库写入；
- 状态更新；
- BKT 更新；
- 候选教学动作过滤；
- Mode 权限约束；
- 阶段进入/退出条件；
- Tool 权限检查；
- 超时、重试、降级；
- 规则型评测；
- Workflow 转移。

LLM 主要用于：

- 开放式语言理解；
- 结构化抽取；
- 高层学习规划；
- 教学回复生成；
- 开放式教学质量评估。

---

# 3. 教学模式

系统支持三种宏观教学模式：

```text
强引导模式
半引导模式
独立模式
```

## 3.1 强引导模式

适合：

- 第一次学习某类作文；
- 某能力明显薄弱；
- 当前需要完整支架。

允许更积极地：

- 带领审题；
- 帮助问题拆解；
- 引导列提纲；
- 提供提示与微课；
- 内容追问；
- 局部示范。

## 3.2 半引导模式

学生完成更多独立工作。

例如：

- 自己审题；
- 自己列提纲；
- 自己写初稿；
- Teacher 主要从反馈和修改阶段介入。

## 3.3 独立模式

接近考试或迁移练习。

学生独立：

- 审题；
- 组织；
- 写作。

写作过程中禁止系统主动：

- 提示结构；
- 提供句型；
- 主动纠错；
- 代写内容。

## 3.4 Mode 必须真正影响系统行为

Mode 必须影响：

- 可用教学动作；
- 是否允许直接提示；
- Tool 权限；
- UI 显示内容；
- Evaluator 检查规则；
- Agent 行为约束。

后续允许按能力维度独立衰减支架，例如：

```text
审题：独立
结构：独立
内容：半引导
语法：半引导
语言优化：强引导
```

---

# 4. 固定模块开发顺序

```text
模块 1  项目骨架与公共 Domain Model
模块 2  Student State
模块 3  Grammar Knowledge Graph
模块 4  RAG / Hybrid Retrieval
模块 5  Grammar Analyzer
模块 6  Pedagogy Policy
模块 7  Agents
模块 8  LangGraph Workflow
模块 9  Adaptive Workspace UI
模块 10 Evaluation
```

开发方式：

> 一个模块完整实现并验收通过后，再进入下一个模块。

不是 MVP → V2 → V3 的反复推倒重构模式。

---

# 5. 模块 1：项目骨架与公共 Domain Model

目标：建立后续全部模块共享的基础设施和类型系统。

至少定义：

```text
学生
作文任务
作文 Draft
教学 Session
教学 Stage
教学 Mode
学生能力状态
知识点状态
错误记录
学习证据
教学动作
教学决策
工具调用记录
评估结果
检索资源
检索结果
```

建议技术：

- Python
- FastAPI
- PostgreSQL
- SQLAlchemy
- Pydantic
- pytest
- 统一配置系统
- 统一日志
- 统一异常处理
- Prompt 集中管理
- Model Provider 抽象

LangGraph 此阶段只搭入口骨架，不提前实现完整教学工作流。

---

# 6. 模块 2：Student State

Student State 是系统核心之一。

## 6.1 状态结构

```text
学生状态

├── 基础画像
│   ├── 年级
│   ├── 学习目标
│   ├── 当前水平
│   └── 学习偏好
│
├── 写作能力状态
│   ├── 审题
│   ├── 结构
│   ├── 内容展开
│   ├── 语法
│   └── 句式表达
│
├── 语法知识状态
│   ├── 各知识节点掌握度
│   ├── 证据数量
│   ├── 最近成功/失败
│   └── 置信度
│
├── 错误模式
│   ├── 高频语法错误
│   ├── 高频结构问题
│   ├── 内容问题
│   └── 句式问题
│
├── 提示依赖
│   ├── 平均提示层级
│   ├── 是否能独立纠错
│   └── 微课后迁移情况
│
└── 当前交互状态
    ├── 当前阶段
    ├── 当前模式
    ├── 连续失败次数
    ├── 当前提示等级
    ├── 当前困惑程度
    └── 当前任务
```

## 6.2 多证据状态

单一知识点不能只存一个 mastery。

至少保留：

- 出现次数；
- 独立发现次数；
- 独立修改次数；
- 所需提示层级；
- 是否需要微课；
- 微课后是否成功；
- 迁移题是否成功；
- 下一篇是否复现；
- 最近证据时间；
- 当前 mastery；
- confidence。

## 6.3 状态更新

离散语法技能：

- 可采用 BKT / Knowledge Tracing。

开放写作能力：

- Rubric Score；
- 历史加权更新；
- EMA / 加权平均。

错误模式：

- LLM Structured Extraction；
- 规则聚合；
- 时间窗口统计。

Student State Manager 是服务模块，不是 Agent。

---

# 7. 模块 3：Grammar Knowledge Graph

## 7.1 一级结构

```text
语法
├── 句子结构
├── 词法
├── 从句与连接
└── 标点与书写规范
```

## 7.2 句子结构

```text
句子结构
├── 简单句
│   ├── 主语 + 谓语
│   ├── 主语 + 谓语 + 宾语
│   ├── 主语 + 系动词 + 表语
│   ├── 主语 + 谓语 + 间接宾语 + 直接宾语
│   └── 主语 + 谓语 + 宾语 + 宾语补足语
│
└── 复杂句
    └── 通过连接结构把简单句组合为更复杂表达
```

## 7.3 词法

```text
词法
├── 动词
│   ├── 时态
│   ├── 主谓一致
│   ├── 被动语态
│   └── 非谓语动词
├── 名词
├── 形容词
├── 副词
├── 代词
├── 介词
└── 冠词
```

## 7.4 图关系

至少支持：

```text
属于
前置知识
容易混淆
常见错误
对应句型
常见标志词
可用于
```

## 7.5 图谱用途

1. 给学生做知识可视化；
2. 给 Planner / Grammar Analyzer 提供结构化知识关系。

支持：

- node 查询；
- prerequisite 查询；
- related concept 查询；
- error → node linking；
- Student State overlay。

第一阶段优先使用 PostgreSQL + NetworkX 等轻量实现，不强制 Neo4j。

---

# 8. 模块 4：RAG / Hybrid Retrieval

RAG 与 Knowledge Graph 职责分离：

```text
Knowledge Graph：
“学什么、知识之间是什么关系”

RAG：
“拿什么材料来教”
```

## 8.1 教学资源类型

至少支持：

```text
作文题
学生作文
范文/优秀段落
语法错误案例
人工纠正案例
基础例句
句式转换案例
语法讲解
结构案例
迁移练习
```

## 8.2 公开数据来源

优先使用许可清晰的公开数据，例如：

- ELLIPSE Corpus
- W&I + LOCNESS / BEA-2019
- JFLEG
- Tatoeba
- 其他经确认可用于研究 / 非商业演示的公开资源

所有外部数据必须保存：

- source；
- 数据集标识；
- license / attribution；
- 数据处理说明。

## 8.3 Resource Metadata

至少包含：

```text
资源编号
内容
资源类型
年级
题型
知识点
能力点
难度
语言水平
来源
许可证
是否人工/公开/生成
```

## 8.4 检索链路

```text
查询理解 / 改写
↓
BM25
+
Dense Retrieval
↓
RRF 融合
↓
Metadata Filter
↓
Rerank
↓
Top-K 教学资源
```

Planner 主要用于：

- 检索下一篇同类作文题；
- 查找迁移任务。

Teaching Agent 主要用于：

- 检索例句；
- 微课材料；
- 错误案例；
- 句式转换案例；
- 结构示例；
- 迁移练习。

---

# 9. 模块 5：Grammar Analyzer

Grammar Analyzer 负责：

> 知道哪里错。

它不负责：

> 决定怎么教。

输入：

- 句子；
- 段落；
- 作文。

结构化输出至少包括：

```text
错误位置
原始表达
正确表达
原句
修改后完整句子
一级类别
对应语法知识点
细分错误类型
原句结构
正确句子结构
结构变化说明
错误原因
置信度
严重程度
对应知识图谱节点
```

要求：

- Structured Output；
- 多错误支持；
- 无错误支持；
- Knowledge Graph node linking；
- 保留 confidence；
- 诊断结果不得直接暴露到学生 UI；
- 输出供 Pedagogy Policy 和 Teaching Agent 使用。

---

# 10. 模块 6：Pedagogy Policy

Pedagogy Policy 回答：

> 当前学生、当前阶段、当前问题下，应该采用什么教学动作？

## 10.1 输入

至少包括：

```text
当前教学阶段
当前问题类型
目标知识点
学生 mastery
mastery confidence
历史错误次数
最近错误复现
上次教学动作
上次动作是否成功
当前教学模式
学生当前意图
连续失败次数
提示依赖
当前困惑/挫败状态
```

## 10.2 候选教学动作

```text
自查
定位提示
概念提示
苏格拉底式追问
问题拆解
对比例子
知识图谱微课
局部示范
直接讲解
迁移练习
独立重试
```

## 10.3 第一阶段算法

```text
阶段约束
↓
模式约束
↓
候选动作过滤
↓
规则 + 启发式评分
↓
Action Ranking
↓
教学决策对象
```

禁止虚构强化学习。

未来有真实数据后才考虑：

- Learning-to-Rank；
- Contextual Bandit。

## 10.4 Policy 输出

```text
教学动作
目标知识点
支架等级
是否允许直接给答案
是否需要练习
练习类型
通过条件
失败后的后续动作
```

---

# 11. 模块 7：Agents

核心只保留三个 Agent。

## 11.1 Planner Agent

负责：

- 学什么；
- 下一阶段；
- 当前教学模式；
- 是否增加/降低支架；
- 是否插入 prerequisite 学习；
- 是否选择下一篇迁移作文；
- 长期学习路径。

不负责具体教学语言。

## 11.2 Teaching Agent

负责：

- 接收 Pedagogy Decision；
- 结合学生状态、作文、检索资源；
- 生成本轮具体教学回复。

禁止：

- 擅自修改 Planner 决策；
- 直接修改 mastery；
- 擅自切换 Mode；
- 越权调用 Tool。

## 11.3 Pedagogy Evaluator

检查：

```text
是否准确针对问题
是否过早暴露答案
支架是否过强
支架是否过弱
是否遵守当前 Mode
是否遵守 Policy
学生下一步是否可执行
是否存在代写
是否与当前教学阶段一致
```

严重违规时：

- 阻止输出；
- 要求 Teaching Agent 重生成。

普通问题可产生 directive。

---

# 12. 学生意图与交互状态识别

学生输入不能只做单标签意图分类。

例如：

> “我还是不会，你直接告诉我吧。”

应识别：

```text
主要意图：请求帮助
次级意图：请求直接答案
困惑程度：较高
挫败程度：中等
```

可融合：

```text
LLM 语义分类
+
向量相似度分类
+
关键词 / 规则
+
Student State 先验
↓
加权融合
```

结果进入 Pedagogy Policy，而不是直接决定答案。

---

# 13. 各教学阶段逻辑

## 13.1 审题

需要识别：

```text
写给谁
写作目的
文体
必须覆盖的要点
主要时态
人称
特殊约束
```

支架路径：

```text
学生独立提取
↓
问题提示
↓
题干定位
↓
拆解示范
↓
必要时直接讲解
```

## 13.2 初稿

根据 Mode 控制 Teacher 介入程度。

独立模式禁止：

- 主动纠错；
- 主动给结构；
- 主动给句型。

## 13.3 语法修改

```text
系统内部诊断
↓
学生自查
↓
定位提示
↓
概念提示
↓
知识图谱微课
↓
回到原句独立修改
↓
迁移练习
↓
必要时直接讲解
```

重复错误允许根据历史状态直接从更高支架层级开始。

## 13.4 结构修改

文章级：

```text
开头
→ 主体
→ 结尾
```

段落级：

```text
主题句
→ 解释
→ 例子/细节
→ 小结/过渡
```

动作：

- 段落概括；
- 找中心句；
- 内容分组；
- 句子重排；
- 结构可视化；
- 对比例文结构。

## 13.5 内容补充

原则：

> 不替学生编核心经历和观点。

路径：

```text
观点
↓
为什么
↓
有没有具体例子
↓
有什么细节
↓
结果 / 感受
```

## 13.6 语言优化

重点：

> 教学生把简单句升级为更成熟的表达。

包括：

```text
添加修饰成分
简单句合并
逻辑关系识别
连接结构
从句升级
句型对比
迁移练习
```

教学时应先引导学生识别句间关系，再构造表达，不能直接一键重写。

## 13.7 二次重写

必须：

- 隐藏完整 AI 修改稿；
- 仅保留 Revision Checklist；
- 学生独立完成 Draft 2。

比较 Draft 1 / Draft 2：

```text
哪些错误消失
哪些错误重复
哪些能力成功迁移
哪些仍依赖提示
是否出现新错误
```

这些形成 Learning Evidence。

## 13.8 最终评估

输出：

1. 面向学生的学习反馈；
2. 面向系统的结构化 Learning Evidence。

Planner 据此决定：

- 下一题；
- Mode 变化；
- 支架变化；
- prerequisite；
- 下一阶段重点。

---

# 14. Agent 与 Tool 交互

Agent 之间：

> 使用结构化 Shared State，不自由聊天。

Agent 与 Tool：

> 使用 Tool Calling / MCP。

## 14.1 内部工具

例如：

- 读取学生状态；
- 写 Learning Evidence；
- 更新 Workflow State；
- BKT 更新；
- Rubric 状态更新；
- 保存 Draft；
- Tool Trace。

## 14.2 适合 MCP 化的能力

优先：

```text
知识图谱服务
教学资源检索服务
题库 / 作文题服务
```

不要求所有内部函数都 MCP 化。

---

# 15. Tool 权限与可靠性

Planner 允许：

```text
读取学生状态
查询知识图谱
搜索作文题
搜索教学资源
```

Planner 禁止：

```text
直接修改学生作文
直接修改 mastery
```

Teaching Agent 允许：

```text
读取相关学生状态
查询知识图谱
检索例句
检索教学材料
```

Teaching Agent 禁止：

```text
擅自修改长期学习计划
擅自切换 Mode
直接修改 mastery
```

Evaluator 允许：

```text
读取教学记录
读取 Policy
读取 Rubric
写评估结果
```

Evaluator 禁止：

```text
直接和学生对话
擅自改变教学计划
```

Tool Runtime 需要：

```text
参数校验
超时
重试
失败降级
调用日志
Execution Trace
```

---

# 16. 模块 8：LangGraph Workflow

整体状态图：

```text
读取 Student State
↓
Planner
↓
确定当前 Stage
↓
诊断 / 当前问题分析
↓
Pedagogy Policy
↓
必要时调用 KG / RAG Tool
↓
Teaching Agent
↓
Pedagogy Evaluator
↓
通过？
├── 否 → 重生成 / 调整
└── 是 → 返回学生
↓
学生响应
↓
生成 Learning Evidence
↓
更新 Student State
↓
阶段通过？
├── 否 → 当前阶段继续
└── 是 → 下一阶段
↓
作文完成？
├── 否 → 继续
└── 是 → 最终评估 / 下一任务规划
```

LangGraph 只负责 orchestration。

具体算法逻辑应保持在独立 service / policy 模块。

---

# 17. 模块 9：Adaptive Workspace UI

前端不是单一聊天窗口。

采用 Component Registry。

至少包含：

```text
作文编辑器
审题卡
教学对话区
语法错误卡
语法知识图谱
微课卡
练习题
段落结构图
内容展开卡
Revision Checklist
学习状态 / 掌握度面板
```

不同 Stage 对应不同组件组合。

示例：

```text
语法阶段
→ 作文 + 错误定位 + 知识图谱 + 微课 / 练习

结构阶段
→ 作文 + 段落结构图 + 调整操作

内容阶段
→ 观点 / 原因 / 例子 / 细节

独立写作
→ 隐藏教学辅助，只保留写作区
```

禁止让 LLM 直接生成任意 React / HTML。

Layout Agent / Layout Policy 只输出结构化 UI 配置。

---

# 18. 模块 10：Evaluation

评测分为在线与离线。

## 18.1 在线 Pedagogy Evaluator

运行时检查 Teaching Agent。

## 18.2 离线评测

采用：

```text
公开 Tutor Benchmark
+
规则自动测试
+
LLM-as-Judge
```

优先参考：

- MRBench
- MathTutorBench
- 其他许可明确的 Tutor Benchmark

无需大量人工标注。

## 18.3 自动规则测试

重点检查：

```text
独立模式是否违规提示
是否跳过学生自查
是否提前直接给答案
内容阶段是否代写
是否违反 Workflow
是否使用越权 Tool
是否错误切换 Mode
```

## 18.4 LLM-as-Judge

用于评估：

```text
问题识别
问题定位
答案暴露
教学策略匹配
指导可执行性
支架强度
模式遵循
教学连贯性
```

## 18.5 消融

至少支持：

```text
普通 LLM Tutor
↓
固定 Prompt Tutor
↓
加入 Student State
↓
加入 Pedagogy Policy
↓
加入 Evaluator
↓
完整系统
```

所有指标必须来自真实运行。

禁止编造效果。

---

# 19. 推荐项目结构

```text
adaptive-writing-tutor/
├── README.md
├── pyproject.toml
├── .env.example
├── docs/
│   └── PROJECT_SPEC.md
├── backend/
│   └── app/
│       ├── api/
│       ├── core/
│       ├── domain/
│       ├── models/
│       ├── schemas/
│       ├── repositories/
│       ├── services/
│       │   ├── student_state/
│       │   ├── knowledge_graph/
│       │   ├── retrieval/
│       │   ├── grammar/
│       │   ├── pedagogy/
│       │   └── evaluation/
│       ├── agents/
│       ├── workflows/
│       ├── tools/
│       ├── prompts/
│       └── db/
├── frontend/
├── data/
│   ├── raw/
│   ├── processed/
│   └── indexes/
├── scripts/
└── tests/
```

实际目录可根据实现做小幅调整，但职责边界不得改变。

---

# 20. 所有模块通用验收标准

任意模块完成后，必须依次执行以下检查。

## 20.1 代码质量检查

检查：

- 未使用代码；
- 明显重复逻辑；
- TODO / FIXME / pass 占位；
- 写死配置；
- 静默吞异常；
- 巨型函数；
- 跨模块职责混乱。

## 20.2 类型与 Schema 检查

检查：

- Pydantic Schema；
- 枚举值；
- 非法字段；
- 缺失字段；
- Agent / Service 接口一致性；
- API 输入输出稳定性。

## 20.3 单元测试

至少覆盖：

- 正常路径；
- 空输入；
- 非法输入；
- 边界输入；
- 重复调用；
- 异常路径。

## 20.4 集成测试

要求：

- 当前模块必须与前置模块真实联通；
- 不允许所有依赖都 mock 后就声称集成成功。

## 20.5 实际运行验证

至少运行一个真实样例。

检查：

- 实际输出；
- 数据库状态；
- 状态变化；
- Tool 调用；
- 文件产物。

## 20.6 架构一致性检查

必须对照本文档确认：

- 是否违反职责边界；
- 是否偷偷增加重复模块；
- 是否把确定性逻辑塞回 Prompt；
- 是否擅自改变 Workflow；
- 是否擅自合并 Agent。

## 20.7 回归检查

当前模块完成后：

> 必须重新运行之前所有已完成模块的重要测试。

不允许：

> 当前模块通过，但破坏已有模块。

## 20.8 文档检查

更新：

- README；
- 模块说明；
- 核心接口；
- 已知限制；
- 外部依赖；
- 数据来源说明。

---

# 21. 各模块专项验收标准

---

## 模块 1：项目骨架与 Domain Model

必须验证：

1. 项目可正常安装依赖；
2. FastAPI 可正常启动；
3. PostgreSQL 可连接；
4. Migration / 初始化流程可运行；
5. 核心 Pydantic Schema 可正确创建与校验；
6. 枚举值非法时正确报错；
7. 配置可从环境变量加载；
8. 日志系统可用；
9. 测试框架可运行；
10. Model Provider 接口可替换；
11. 不存在核心业务逻辑被提前塞入本模块；
12. 项目目录和 import 路径稳定。

---

## 模块 2：Student State

必须验证：

1. 新学生初始化；
2. 写入 Learning Evidence；
3. mastery 更新；
4. confidence 更新；
5. 重复错误累计；
6. 提示依赖统计；
7. BKT 连续成功后的状态变化；
8. BKT 连续失败后的状态变化；
9. 同一 Evidence 重复提交不会重复计数；
10. 数据库重启后状态仍存在；
11. 多学生状态互不污染；
12. 开放式写作能力更新逻辑正确；
13. 历史时间窗口统计正确；
14. Planner / Policy 可通过统一接口直接读取状态；
15. Student State Manager 未被实现成聊天 Agent。

---

## 模块 3：Knowledge Graph

必须验证：

1. 核心语法节点完整；
2. parent / child 查询；
3. prerequisite 查询；
4. related concept 查询；
5. error → node linking；
6. 不存在节点时合理处理；
7. 关键节点不存在孤立情况；
8. prerequisite 不存在非法循环；
9. Student State overlay 可正确关联；
10. 节点唯一标识稳定；
11. 图关系方向一致；
12. 小规模查询性能满足演示需要；
13. KG 与 RAG 仍保持职责分离。

---

## 模块 4：RAG / Hybrid Retrieval

必须验证：

1. 至少一批公开数据成功导入；
2. source / license / attribution 保存正确；
3. Resource Metadata 完整；
4. BM25 能召回关键词高度匹配结果；
5. Dense Retrieval 能召回语义近似结果；
6. RRF 真正融合两路排序；
7. Metadata Filter 生效；
8. Rerank 能改变候选结果排序；
9. 空查询正确处理；
10. 无结果查询正确处理；
11. Top-K 输出 Schema 稳定；
12. 固定 Query Set 可用于回归；
13. 重建索引可复现；
14. 不同资源类型可过滤；
15. 检索结果可被 Planner / Teaching Agent 使用；
16. 不使用来源不明的网页内容填库。

---

## 模块 5：Grammar Analyzer

必须验证：

1. 无错误句子；
2. 单错误句子；
3. 多错误句子；
4. 时态错误；
5. 主谓一致；
6. 冠词；
7. 句子结构错误；
8. 每个错误能映射到 KG node；
9. 输出正确句子结构；
10. confidence 字段存在且合法；
11. severity 合法；
12. 多错误顺序稳定；
13. 无法确定时允许低置信度而不是强行判断；
14. Analyzer 不负责教学策略；
15. 原始诊断结果不会直接出现在学生 UI。

---

## 模块 6：Pedagogy Policy

必须验证：

1. 高 mastery + 首次错误 → 优先轻支架；
2. 连续失败 → 支架升级；
3. 重复错误 → 可进入微课；
4. 独立模式 → 禁止违规提示；
5. 强引导模式 → 允许更强支架；
6. 学生要求“直接告诉我”不能绕过 Policy；
7. 直接讲解有明确触发条件；
8. 候选动作过滤正确；
9. Ranking 分数可解释；
10. 相同输入应得到稳定结果；
11. 模式约束优先于 LLM 意图；
12. Policy 输出完整结构化对象；
13. Policy 不生成面向学生的自然语言回复；
14. 不存在“把所有决策交给 LLM”的旁路。

---

## 模块 7：Agents

### Planner 必须验证

1. 不生成具体教学话术；
2. 不直接修改 mastery；
3. 可根据 Student State 调整学习目标；
4. 可切换 Mode；
5. 可插入 prerequisite；
6. 可选择下一篇迁移任务；
7. 输出结构化。

### Teaching Agent 必须验证

1. 严格遵守 Pedagogy Decision；
2. 不自行改变 Planner 目标；
3. 不自行改变 Mode；
4. 不越权 Tool；
5. 可正确使用 KG / RAG 返回资源；
6. 不直接写长期 Student State；
7. 输出符合当前 Stage。

### Evaluator 必须验证

1. 可识别答案提前暴露；
2. 可识别支架过强；
3. 可识别支架过弱；
4. 可识别 Mode 违规；
5. 可识别代写；
6. 可识别未遵守 Policy；
7. 严重违规可触发重生成；
8. Evaluator 自身不直接回复学生。

---

## 模块 8：LangGraph Workflow

必须验证：

1. 正常完整走完一篇作文；
2. 某阶段失败时停留当前阶段；
3. 达到通过条件后进入下一阶段；
4. 独立模式不提前介入；
5. Evaluator 拒绝后触发重生成；
6. Student State 在正确时机更新；
7. Workflow 中断后可恢复；
8. 重复请求不会推进两次；
9. Tool 失败时存在降级；
10. 无死循环；
11. 最大重试次数生效；
12. 阶段进入/退出条件可测试；
13. Shared State 字段完整；
14. LangGraph 只做 orchestration，不吸收 service 逻辑。

---

## 模块 9：Adaptive Workspace UI

必须验证：

1. 不同 Stage 显示不同组件；
2. 独立模式隐藏辅助组件；
3. Grammar Stage 可显示 KG；
4. Structure Stage 显示结构视图；
5. Content Stage 显示内容展开组件；
6. Rewrite 阶段隐藏完整 AI 修改稿；
7. 后端状态可驱动 UI；
8. 页面刷新后 Session 不丢失；
9. 空状态展示合理；
10. API 错误展示合理；
11. Loading 状态合理；
12. Component Registry 工作正常；
13. LLM 未直接生成前端代码；
14. UI 与 Mode 权限一致。

---

## 模块 10：Evaluation

必须验证：

1. 规则评测可自动运行；
2. LLM Judge 输出结构化；
3. Benchmark 输入适配正确；
4. 至少可比较多个系统配置；
5. 所有指标来自真实运行；
6. 不存在硬编码优胜结果；
7. 结果可保存；
8. 结果可复现；
9. 评测配置可追踪；
10. Rule-based 与 LLM-based 指标区分清楚；
11. Benchmark 数据许可说明保留；
12. 消融配置可独立运行。

---

# 22. 每个模块完成报告格式

每个模块完成后，必须输出：

```text
模块名称：

一、已实现能力
-

二、核心新增/修改文件
-

三、核心接口
-

四、执行的检查与测试
-

五、测试结果
-

六、发现并修复的问题
-

七、已知限制
-

八、回归结果
-

九、是否满足本模块验收标准
是 / 否

十、是否具备进入下一模块的条件
是 / 否
```

如果第九项为“否”：

> 不得进入下一模块。

必须继续修复、测试、重新验收。

---

# 23. Codex 自动开发行为规范

Codex 在整个项目中应遵守：

```text
读取本文档
↓
开发当前模块
↓
运行通用验收
↓
运行模块专项验收
↓
发现问题
├── 有 → 自行修复并重新测试
└── 无
↓
运行回归测试
↓
更新文档
↓
输出模块完成报告
↓
全部通过？
├── 否 → 继续修复
└── 是 → 自动进入下一模块
```

普通工程细节无需询问用户。

只有以下情况才停止：

- 需要 API Key / 账号 / 外部权限；
- 涉及不可逆数据删除；
- 存在真正会改变产品行为的设计歧义；
- 总架构存在明确技术冲突。

---

# 24. 开发纪律

必须遵守：

- 一个模块一个模块开发；
- 当前模块未验证通过，不进入下一模块；
- 不把核心逻辑写成巨大 Prompt；
- 不创建未来必然废弃的平行架构；
- 不虚构未实现功能；
- 不虚构 Benchmark 数字；
- 不为简历关键词无意义堆技术；
- 不擅自改变 Workflow；
- 不擅自改变 Agent 职责；
- 不把 Student State Manager 改成 Agent；
- 不把 KG 与 RAG 混为一体；
- 不把 Pedagogy Policy 交给 LLM 自由决定；
- 所有关键状态和决策尽可能结构化、可测试、可追踪。

---

# 25. 项目最终技术故事

最终系统最重要的三个技术点：

## Stateful Agent Workflow

将长期英语写作教学组织为可控状态机，并根据学生能力动态降低支架与切换教学模式。

## Student Model + Pedagogy Policy

基于知识掌握度、历史错误、提示依赖、实时意图等状态选择具体教学动作，而不是让 LLM 凭感觉教学。

## Knowledge + Retrieval + Evaluation

使用 Knowledge Graph 支持知识路径规划，Hybrid Retrieval 提供教学材料，并通过独立教学质量评估约束 Tutor 是否真正“会教”。

---

# 26. 最高优先级原则

如果实现过程中必须在：

```text
快速
炫技
架构一致性
```

之间选择：

> 优先保证架构一致性、模块边界、可测试性和真实可运行。
