# 模块 4：Redis 检索结果缓存补充验收（2026-10-27）

模块名称：RAG / Hybrid Retrieval（模块 8 Tool 调用接线）

一、已实现能力
- `RetrievalRuntime` 在 FastAPI lifespan 内创建并复用一个 Redis 客户端；`HybridRetriever.search` 采用 cache-aside，命中直接返回经过 Schema 校验的结构化结果。
- 键包含完整查询及过滤条件、`top_k`、`rrf_k` 和索引版本。重建索引产生新版本，旧条目不能命中新快照，并在 TTL 到期后清除。
- 默认 TTL 300 秒。Redis 不可用时在短超时后执行原检索并暂缓重试；缓存内容损坏时删除并重新计算。
- 不缓存学生状态、模型回复、学生作文和人工纠错资源。每次 Tool 调用仍执行权限检查与 Trace 记录。

二、核心新增/修改文件
- `backend/app/services/retrieval/cache.py`、`backend/app/services/retrieval/{hybrid,runtime}.py`、`backend/app/core/config.py`。
- `tests/test_retrieval_cache.py`、`scripts/demo_retrieval_cache_live.py`。
- `pyproject.toml`、`.env.example`、`README.md`、`docs/{MODULE_04,MODULE_08}.md`。

三、核心接口
- `RedisRetrievalCache.key(index_version, query)` / `get(...)` / `put(...)`。
- `HybridRetriever.search(RetrievalQuery)`：缓存命中、实时检索和结果回填统一入口。
- `RETRIEVAL_CACHE_ENABLED`、`REDIS_URL`、`RETRIEVAL_CACHE_TTL_SECONDS`、`RETRIEVAL_CACHE_TIMEOUT_SECONDS`、`RETRIEVAL_CACHE_RETRY_SECONDS`。

四、执行的检查与测试
- 检查全部查询字段与索引版本参与键计算；测试 TTL、空结果、损坏数据、学生资源跳过、跨客户端命中、版本切换、Redis 断开与恢复。
- 使用真实 PostgreSQL 语料和本地 FastEmbed 索引测试 Retriever，并通过 Tool Runtime 验证缓存命中仍有权限控制与 Trace。
- 在真实 Redis 8.10.2 上运行 `scripts/demo_retrieval_cache_live.py`；在 Redis 连接下运行 DeepSeek + PostgreSQL 的真实 HTTP 工作流样例。
- 对照 `PROJECT_SPEC.md` 执行模块 4 专项与所有模块通用验收、前置模块回归、Ruff、mypy、前端构建及 Alembic 漂移检查。

五、测试结果
- 后端 113 项通过；前端 29 项通过并完成生产构建；Ruff、mypy、Alembic 检查通过。
- 真实 Redis 样例使用 139 条资源：缓存命中及第二个客户端命中均为 `true`，重建索引后新版本缓存未命中为 `true`，新条目 TTL 为 300 秒。
- 真实 DeepSeek 工作流完成两次 HTTP 提交并进入 `first_draft`，记录 4 次 Tool 调用，学生的题目分析能力证据计数增至 1。

六、发现并修复的问题
- 原有运行时只有进程内检索快照，没有跨进程结果复用；新增 Redis 结果缓存。
- 缓存故障可能放大请求延迟；加入 0.2 秒默认超时与 30 秒重试间隔，保持实时检索可用。
- 学生作文和人工纠错类型可能含个人内容；缓存读写均拒绝这两类资源。

七、已知限制
- 现有本机检索中位数约 1.769 ms，尚无真实负载下的 Redis 命中率、P95 延迟或吞吐量提升数据；不宣称缓存已带来整体性能收益。
- Redis 需要独立服务及运维侧内存上限；TTL 会清理旧版本条目，但不会在每次重建时全量扫描删除。
- 高并发同键首次未命中时可能重复检索；当前未加入分布式防击穿锁。

八、回归结果
- 模块 1–10 后端 113 项测试、前端 29 项测试、真实 HTTP 样例和数据库迁移检查全部通过；Knowledge Graph、Student State、Pedagogy Policy 与 Agent 边界未变。

九、是否满足本模块验收标准
是

十、是否具备进入下一模块的条件
是（本次为已完成模块的运行时增补，不改变十模块顺序）
