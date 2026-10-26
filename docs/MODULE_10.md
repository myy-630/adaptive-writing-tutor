# 模块 10：Evaluation

## 边界与实现

在线 `PedagogyEvaluator` 仍由生产工作流调用，在教学文本交给学生前独立执行检查；模块 10 新增的是离线评测服务，位于 `backend/app/services/evaluation`，不会接管 Planner、Policy 或 Teaching Agent 的职责。离线评测由三部分组成：确定性规则、结构化 LLM Judge、公开 Tutor Benchmark 适配与校准。

`RuleEvaluator` 对可观察的会话输出检查七类情况：独立模式教学介入、跳过学生自查、提前暴露答案、内容阶段近似整段代写、固定 Workflow 阶段顺序、越权 Tool、Mode 不一致。每项保存 `applicable` 标志；规则通过率只统计适用检查。规则是保守启发式，不能代替人工或 LLM 的教学质量判断。版本 3 修复了 Markdown 拆词导致的答案泄漏漏检，并避免把“what small change…”误判为直接修改指令。

`StructuredTutorJudge` 通过现有 Model Provider 请求 Pydantic 结构化输出，评估问题识别、定位、答案暴露、教学策略匹配、可执行性、支架强度、模式遵循、连贯性，额外记录代写标志和理由。没有可依据的策略或 Mode 时对应维度必须为 `null`。Judge 指标与规则指标分别保存；Judge 不参与生产阶段推进，也不能改写学生看到的教学文本。本轮生成与 Judge 都使用 DeepSeek，存在同源模型偏差，尚无充分的人类校准。

## Benchmark 与许可

`benchmark.py` 读取 [MRBench V1 官方发布](https://github.com/kaushal0494/UnifyingAITutorEvaluation)中的 MathDial `test` 来源行，验证本地 SHA-256 与许可清单，保留原始导师回复、八维人工标注和对话 ID。仓库只保存按上游顺序筛选的四个 MathDial 对话；该衍生样本采用 MRBench 的 [CC BY-SA 4.0](../data/processed/MRBENCH_LICENSE.md)，MathDial 的原始许可见[发布页面](https://huggingface.co/datasets/eth-nlped/mathdial)。Bridge 来源行未纳入。官方 [MathTutorBench](https://github.com/eth-lre/mathtutorbench)作为评测设计参考，本模块没有导入其数据。

这份公开样本是**数学辅导 Judge 校准样本**，不是英语作文评测集。真实校准调用了两个已有标注的导师回复，对五个可对齐的二值维度计算一致率；它只能证明适配与运行链路可用，不能代表 Judge 的总体准确率。项目另外提供一个明确标记为 `project-authored` 的英语写作评测案例，用于配置对比，不称作公开 Benchmark。

## 消融配置与运行

`AblationRunner` 支持六个独立配置；每个配置的开关保存在报告中：

| 配置 | 固定提示 | Student State | Pedagogy Policy | Pedagogy Evaluator | 完整 Workflow |
| --- | --- | --- | --- | --- | --- |
| `ordinary_llm` | 否 | 否 | 否 | 否 | 否 |
| `fixed_prompt` | 是 | 否 | 否 | 否 | 否 |
| `student_state` | 是 | 是 | 否 | 否 | 否 |
| `pedagogy_policy` | 是 | 是 | 是 | 否 | 否 |
| `pedagogy_evaluator` | 是 | 是 | 是 | 是 | 否 |
| `full_system` | 是 | 是 | 是 | 是 | 是 |

Policy 配置实际调用生产 `PedagogyPolicy.decide`；Evaluator 配置实际调用生产 `PedagogyEvaluator.evaluate` 并按上限重生成；完整系统配置通过真实 FastAPI → LangGraph 工作流运行，读取 PostgreSQL Tool Trace。前三个配置是离线基线，不改变生产系统。`scripts/run_evaluation_live.py` 默认运行普通 LLM 与完整系统，可用 `--variants` 选择任意配置组合；六种配置均有独立运行测试。单独的 `pedagogy_policy` 也完成真实 DeepSeek 运行。

运行命令：

```bash
.venv/bin/python scripts/run_evaluation_live.py
.venv/bin/python scripts/run_evaluation_live.py --variants pedagogy_policy --skip-calibration
.venv/bin/python scripts/replay_evaluation.py reports/evaluation/module10-writing-measured.json
.venv/bin/python scripts/replay_evaluation.py reports/evaluation/module10-mrbench-calibration.json
```

报告保存原始回复、规则逐项结果、Judge 结构化判断、模型名称、数据集 SHA-256、消融开关、规则版本和配置 SHA-256。`replay_evaluation.py` 从冻结结果重算汇总，校验数据与配置哈希，不再次调用模型；新的模型运行可能因采样和服务变化产生不同文本。规则修正时 `rescore_evaluation.py` 从冻结的真实回复重算，记录原始报告 SHA-256，保留完整来历。

## 本轮真实观测

在一个项目自编的语法案例上，[规则版本 3 的对比报告](../reports/evaluation/module10-writing-measured.json)包含普通 LLM 与完整系统各一次真实 DeepSeek 回复。普通 LLM 的回复明确给出 `goes`，规则记录 `early_answer_exposure`，Judge 也标记答案暴露；完整系统的回复采取 `location_hint`，在线 Evaluator 为 `pass`，9 条工具调用有真实记录，规则未发现适用项违规。规则通过率分别为 0.75 与 1.0，分母为各自适用的规则项，**不是学生学习效果或总体系统胜率**。[Policy 单独运行报告](../reports/evaluation/module10-policy-ablation.json)也来自真实调用。

[MRBench 校准报告](../reports/evaluation/module10-mrbench-calibration.json)包含两个数学辅导回复，五个二值维度在这两个样本上均与原标注一致。样本极小，不能外推。所有上述数字均由保存的真实模型输出、规则结果和 Judge 调用计算；没有预设优胜配置。详细测试包括正常、空、非法、边界、重复与异常路径，以及完整前置模块回归。
