# Adaptive Writing Tutor

面向初高中英语写作的状态化、自适应教学系统。项目按 [最高设计与验收规范](docs/PROJECT_SPEC.md) 的十个模块顺序实施。模块 1–10 已按固定顺序完成，模块验收报告保存在 `docs/MODULE_*_REPORT.md`。

## 许可证与数据

项目代码及文档采用 [MIT 许可证](LICENSE)。随仓库提供的第三方样本数据沿用各自的许可证，不在 MIT 授权范围内：

- `data/processed/tatoeba_sample.jsonl`：Tatoeba 英语句子，逐条记录作者、来源与 CC BY 2.0 FR 许可证；筛选方式见 [模块 4 说明](docs/MODULE_04.md)。
- `data/processed/mrbench_mathdial_v1_sample.jsonl`：MRBench MathDial 四段对话，按 CC BY-SA 4.0 发布；原始来源、改动和 MathDial 的 CC BY 4.0 许可见 [数据署名说明](data/processed/MRBENCH_LICENSE.md)。
- `data/processed/writing_eval_cases.jsonl`：项目自编的评测示例，采用 MIT 许可证。

本地 `.env`、数据库、下载的模型与索引、依赖目录均不会提交。公开仓库中的演示与评测结果不含真实学生个人数据。

## 当前可运行能力

- FastAPI 入口、数据库健康检查、统一配置与日志。
- 共享 Pydantic Domain Model，包括学生、任务、草稿、教学会话、状态、证据、教学决策、工具调用、评估和检索资源。
- PostgreSQL 的学生、作文任务、草稿、教学会话基础表及 Alembic 迁移。
- Student State Manager：事务化学生初始化、学习证据去重、BKT、开放能力 EMA、提示依赖和分时间窗口的错误模式统计。
- Grammar Knowledge Graph：稳定知识节点、七类有向关系、前置知识检查、错误映射和学生掌握度叠加。
- 语法多步学习路径：当前错误的前置知识拓扑排序、长期薄弱点复习分支、三状态掌握度判断与进出门槛；详见 [语法学习路径](docs/GRAMMAR_LEARNING_PATH.md)。
- Hybrid Retrieval：133 条带署名与许可的公开 Tatoeba 句子、6 条明确标记的项目演示资源、BM25 + 本地 dense + RRF + Metadata Filter + Rerank；索引和模型在 FastAPI lifespan 中按进程复用，并按索引版本热切换。[运行时与缓存策略](docs/MODULE_04.md#运行时复用与缓存决策)。
- Grammar Analyzer：保守规则诊断，输出错误位置、修改后完整句子、结构变化、置信度和知识图谱节点；诊断结果不直接进入学生 UI。
- Pedagogy Policy：依据阶段、模式、学生状态与当前意图，对教学动作做硬约束过滤和可解释排序，输出结构化教学决策。
- Planner、Teaching Agent、独立 Pedagogy Evaluator，带工具权限、重试降级与 PostgreSQL Trace；DeepSeek Responses 适配器已完成真实调用验收。
- LangGraph 八阶段作文工作流、PostgreSQL checkpoint 恢复、请求去重、有界重生成、五维过程性量表证据与能力 EMA、工作流 HTTP 接口；详见 [模块 8 说明](docs/MODULE_08.md)和[量表标准](docs/ABILITY_RUBRIC.md)。
- React Adaptive Workspace：固定 Component Registry、按 Stage/Mode 组合的 11 个教学与写作组件、Session 刷新恢复、加载及错误状态；详见 [模块 9 说明](docs/MODULE_09.md)。
- Evaluation：生产在线 Pedagogy Evaluator、离线七类规则、结构化 LLM Judge、带许可记录的 MRBench MathDial 适配、六配置消融、真实结果保存与冻结重放；详见 [模块 10 说明](docs/MODULE_10.md)。

一次真实浏览器与 DeepSeek 的八阶段示例见[全流程演示记录](docs/DEMO_FULL_WORKFLOW_2026-10-26.md)。
量表接线的实现范围和实测结果见[补充验收记录](docs/ABILITY_RUBRIC_REPORT_2026-10-27.md)。
检索器的进程复用、索引版本切换和缓存测量见[运行时补充验收记录](docs/RETRIEVAL_RUNTIME_REPORT_2026-10-27.md)。

## 本地启动

当前实际验证环境为 Python 3.14、Node.js 24、PostgreSQL 18。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
# 修改 .env 中的 DATABASE_URL 和 DEEPSEEK_API_KEY，确保数据库已创建且可连接
.venv/bin/alembic upgrade head
.venv/bin/python scripts/seed_grammar_graph.py
.venv/bin/python scripts/import_tatoeba_sample.py
.venv/bin/python scripts/seed_demo_resources.py
.venv/bin/python scripts/download_embedding_model.py
.venv/bin/python scripts/build_retrieval_index.py
.venv/bin/uvicorn app.api.main:app --reload
```

另开终端运行前端：

```bash
cd frontend
npm ci
npm run dev
```

前端开发地址为 `http://127.0.0.1:5173/`，Vite 将 `/students`、`/tasks`、`/sessions` 代理到本机 8000 端口。生产部署可设置 `VITE_API_BASE_URL` 指向后端；该变量进入浏览器构建，不能包含密钥。DeepSeek 密钥只放在根目录私有 `.env`，不得写进前端。

访问 `/health/live` 检查进程，访问 `/health/ready` 检查 PostgreSQL 连接。运行测试：

```bash
.venv/bin/pytest -q
.venv/bin/ruff check backend tests scripts
.venv/bin/mypy backend/app --ignore-missing-imports
.venv/bin/alembic check
cd frontend && npm run build && npm test
```

运行离线真实评测（会调用所配置的模型服务，并写入 `reports/evaluation/`）：

```bash
.venv/bin/python scripts/run_evaluation_live.py
.venv/bin/python scripts/replay_evaluation.py reports/evaluation/module10-writing-measured.json
```

数据库集成测试要求 `DATABASE_URL` 指向已执行最新迁移的独立测试数据库。测试会写入示例记录，请勿将生产数据库用作测试目标。

## 目录与接口

- `backend/app/domain`：共享枚举和 Pydantic Schema。
- `backend/app/models`：SQLAlchemy 持久化模型。
- `backend/app/db`、`backend/migrations`：数据库连接和迁移。
- `backend/app/core`：配置、日志、异常和 Model Provider 接口。
- `backend/app/api/main.py`：`create_app(settings, provider)` 应用工厂与健康端点。
- `backend/app/services`：后续服务模块各自实现，不把服务决策塞入 Agent Prompt。
- `backend/app/services/student_state`：`StudentStateManager` 与 `StudentStateReader` 统一接口，详见 [模块 2 说明](docs/MODULE_02.md)。
- `backend/app/services/knowledge_graph`：语法图谱种子、校验及查询，详见 [模块 3 说明](docs/MODULE_03.md)。
- `backend/app/services/retrieval`：教学资源存储、索引和混合检索，详见 [模块 4 说明](docs/MODULE_04.md)。
- `backend/app/services/grammar`：内部结构化诊断，详见 [模块 5 说明](docs/MODULE_05.md)。
- `backend/app/services/pedagogy`：确定性教学动作过滤和排序，详见 [模块 6 说明](docs/MODULE_06.md)。
- `backend/app/agents`：模块 7 的 Planner、Teaching Agent、独立 Evaluator 和工具运行时，详见 [模块 7 说明](docs/MODULE_07.md)。
- `backend/app/workflows`：模块 8 LangGraph 编排与独立阶段服务，详见 [模块 8 说明](docs/MODULE_08.md)。
- `frontend/src/layout.ts`：确定性 Stage/Mode 布局配置。
- `frontend/src/components.tsx`：固定 Component Registry 和 11 个工作区组件。
- `frontend/src/App.tsx`、`api.ts`：会话恢复、表单、请求与状态呈现，详见 [模块 9 说明](docs/MODULE_09.md)。
- `backend/app/services/evaluation`：模块 10 离线规则、Judge、Benchmark 适配、消融及报告重放，详见 [模块 10 说明](docs/MODULE_10.md)。

公开数据目前包括 Tatoeba 英语句子与四个 MRBench MathDial 来源的数学辅导对话。后者仅用于 Judge 适配与小样本校准；尚无公开英语作文错误改写 Benchmark，现有单案例消融结果不代表整体教学效果。HTTP 会话目前依赖学生 UUID 归属校验，尚无生产级账号认证。
