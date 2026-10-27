# 模块 4 运行时缓存改造补充验收（2026-10-27）

此文记录首次运行时改造时的验收状态；后续已按用户要求加入 Redis 结果缓存，当前状态见 [Redis 补充验收](REDIS_CACHE_REPORT_2026-10-27.md)。

模块名称：RAG / Hybrid Retrieval（模块 8 工作流接线）

一、已实现能力
- FastAPI lifespan 为每个进程初始化数据库会话工厂、模型 Provider 和只读检索快照；Workflow 请求复用同一检索器。
- 重建索引生成唯一版本，分别写入向量文件与元数据；请求通过元数据版本发现变化，加载完整新快照后切换引用。
- 缺失、损坏、语料过期或模型不匹配时走既有 Tool 降级路径；两个索引文件版本不一致时保留旧快照并在后续请求重试。
- Student State 按请求读取数据库，模型回复按调用生成；此轮尚未启用跨请求检索结果缓存。

二、核心新增/修改文件
- `backend/app/services/retrieval/runtime.py`、`backend/app/services/retrieval/{hybrid,schemas}.py`。
- `backend/app/api/{main,workflow}.py`、`scripts/benchmark_retrieval_runtime.py`。
- `tests/{test_retrieval_runtime,test_module4_retrieval}.py`、`docs/{MODULE_04,MODULE_08}.md`、`README.md`。

三、核心接口
- `RetrievalRuntime.current()`：取得当前版本的进程内检索快照，版本变化时重新加载。
- `RetrievalRuntime.loaded_version`：报告当前已加载的索引版本。
- `HybridRetriever.build_index()` / `load_index()`：发布和验证索引版本。

四、执行的检查与测试
- 运行模块 4 专项测试、HTTP lifespan 复用、索引缺失后恢复、版本切换、半发布状态、损坏元数据恢复、并发请求和旧索引兼容测试。
- 运行所有后端模块回归、前端测试与构建、Ruff、mypy、Alembic 漂移检查。
- 运行本地检索计时脚本及 DeepSeek + PostgreSQL 的真实 HTTP 作文阶段样例。
- 对照 `PROJECT_SPEC.md` 检查：RAG 与 Knowledge Graph 分离，Student State Manager 仍为服务，Tool 权限与 Trace 保持在既有工作流，检索版本切换为确定性代码。

五、测试结果
- 后端 106 项测试全部通过；前端 29 项测试和生产构建通过；Ruff、mypy 及 Alembic 检查通过。
- 139 条资源的本机 20 次定向计时：旧流程每次加载中位数 43.803 ms（5 次范围 43.249–63.846 ms）；新流程启动加载 49.55 ms、版本检查中位数 0.052 ms、检索中位数 1.769 ms。该结果不能代表生产吞吐量。
- 真实 HTTP 样例完成 `start` 和 `prompt_analysis` 两次提交；DeepSeek 请求成功，工作流进入 `first_draft`，记录 4 次 Tool 调用，学生能力证据计数增至 1。

六、发现并修复的问题
- 原 Workflow 每次提交都重新读语料、载入索引并构造 FastEmbed 模型；改为每个进程只在启动或索引版本变化时加载。
- 原索引文件没有显式版本，无法在语料不变的重建后识别新快照；加入版本双文件校验，并兼容旧文件。
- 全量格式检查发现 Student State Manager 中两处既有缩进不符合 Ruff 格式；仅调整空白字符。

七、已知限制
- 此轮尚未缓存检索结果；后续用户明确要求加入 Redis，当前实现见链接的补充验收。
- 每个进程各持有一份检索快照；索引版本检查涉及一次本地元数据读取。语料导入后需执行建索引脚本发布新版本。
- 索引文件是本机产物，部署时需在各进程可读的路径构建或分发；本次没有测量多机发布时延。

八、回归结果
- 模块 1–10 的 106 项后端测试、前端 29 项测试及真实 HTTP 样例通过；既有数据库 Schema 无漂移。

九、是否满足本模块验收标准
是

十、是否具备进入下一模块的条件
是（本次为已完成模块的运行时增补，不改变十模块顺序）
