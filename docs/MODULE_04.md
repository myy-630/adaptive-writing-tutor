# 模块 4：RAG / Hybrid Retrieval

## 资源与来源

当前公开样本为 133 条英语句子，保存在 `data/processed/tatoeba_sample.jsonl`，文件 SHA-256 为 `f6feb35fdf8199f545bab468f799ff9e6673e2935c18633ee3fe6835ba43e982`。每条资源保存 Tatoeba 句子 ID、作者、逐条许可证、原始页面 URL、导入条件和处理说明。官方 API 查询限定为英文、`CC BY 2.0 FR`、已审核、非孤儿句、5–20 词；仅保留 ASCII 且长度在 30–180 字符的原文，没有修改文本。Tatoeba 的[官方语料使用说明](https://en.wiki.tatoeba.org/articles/show/using-the-tatoeba-corpus)和[官方 API 文档](https://api.tatoeba.org/openapi.json)说明许可、作者和查询字段。

另有 6 条项目内生成的演示资源，显式标记为 `generated`，许可证字段写为 `Project-generated demo content`，不当作公开语料或 Benchmark。它们用于验证作文题、语法讲解、迁移练习、结构示例和句式转换的过滤与接口。

## 检索链路

```text
查询归一化与少量确定性词形扩展
→ BM25 + BGE-small-en-v1.5 384 维本地 dense
→ RRF 融合
→ 年级 / 题型 / 知识点 / 能力点 / 难度 / 语言等级 / 类型过滤
→ 词项覆盖、短语匹配和例句长度启发式重排
→ Top-K RetrievalResult
```

Dense 模型由 FastEmbed 加载，其[模型卡](https://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q)标记为 MIT 许可。首次下载可能较慢；模型权重与 `.npz` 索引保存在本地 `data/indexes/` 并被 Git 忽略。索引元数据保存唯一索引版本、语料哈希、模型名、FastEmbed 版本、资源数和向量维度；加载时验证匹配，不匹配则要求重建。旧版无版本号索引按 `legacy` 读取，首次重建后升级为显式版本。重建后向量和固定 Query Set 排序均通过回归测试。

## 运行时复用与 Redis 结果缓存

按 [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) 的生命周期，应用为每个进程创建一次数据库会话工厂、只读 `RetrievalRuntime` 和模型 Provider。`RetrievalRuntime` 在启动时加载语料、BM25、FastEmbed 模型及向量索引；每个 Workflow 请求只读取小型元数据文件中的 `index_version`。版本未变时复用同一个检索快照；运行 `scripts/build_retrieval_index.py` 重建索引会产生新版本，下一次请求将完整加载新快照并一次性切换引用。已经取得旧快照的请求可以继续检索；切换时新进入的请求等待加载完成。索引与元数据文件的版本不一致时保留原快照，待发布完成后重试。缺失、过期或损坏的索引沿用 Tool Runtime 的降级路径。历史索引与新索引都必须匹配数据库语料哈希。

2026-10-27 本机 139 条资源的定向测量（`scripts/benchmark_retrieval_runtime.py --iterations 20`）：旧实现每次加载索引和模型的中位数为 43.803 ms（5 次范围 43.249–63.846 ms）；改造后一次启动加载为 49.55 ms，请求内版本检查中位数 0.052 ms，重复检索中位数 1.769 ms。样本量和机器范围有限，不能据此声称 Redis 改善了整体吞吐量或教学效果。

按用户要求，Workflow 中的检索结果现采用 Redis [cache-aside](https://redis.io/docs/latest/develop/use-cases/cache-aside/)。每个进程的 `RetrievalRuntime` 复用一个 redis-py 客户端；第一次查询计算检索结果并用 `SET EX` 写入，后续同键查询通过 `GET` 返回。键使用完整 `RetrievalQuery` 的稳定 JSON（文本、知识点及全部其他过滤条件、`top_k`）与 `rrf_k` 的 SHA-256，并以 `index_version` 分命名空间；不把学生输入明文放进键。默认 TTL 300 秒，可通过 `RETRIEVAL_CACHE_TTL_SECONDS` 修改。重建索引后新版本必定未命中旧缓存，旧版本条目在 TTL 到期后删除。缓存只保存结构化检索资源及排序，不保存学生状态或模型回复；作文原文和人工纠错类型也不写入共享缓存。Tool 权限检查与调用 Trace 均在缓存外执行。

Redis 连接超时默认 0.2 秒；连接失败时记录一次告警，接下来的 30 秒直接运行原检索，之后重试连接。无效缓存内容会删除并重新检索。可设置 `RETRIEVAL_CACHE_ENABLED=false` 关闭结果缓存；Redis 服务未启动时教学请求仍可正常运行，但没有缓存命中。Redis URL 可通过私有 `.env` 的 `REDIS_URL` 设置，密码不要提交。真实 Redis 功能样例：`REDIS_URL=redis://127.0.0.1:6379/0 .venv/bin/python scripts/demo_retrieval_cache_live.py`。

## 核心接口

- `ResourceStore.import_jsonl` / `add_resources` / `list_resources`：元数据验证、入库和重复导入保护。
- `HybridRetriever.build_index` / `load_index` / `search(RetrievalQuery)`：索引构建和结构化 Top-K 检索。
- `RedisRetrievalCache.get` / `put`：按查询与索引版本读写有 TTL 的结果缓存；Redis 不可用时降级。
- `HybridRetriever.find_writing_prompts`：供 Planner 搜索下一题。
- `HybridRetriever.find_teaching_material`：供 Teaching Agent 搜索例句、微课、结构案例及练习。
- `tests/fixtures/retrieval_queries.json`：固定回归查询。

Knowledge Graph 与 RAG 代码分离。检索资源可携带稳定知识点 ID 作过滤，但检索服务不执行图谱查询或学习路径决策。

## 已知限制

- 公开样本目前只有基础句子，尚未导入公开作文、人工纠错或错误案例；相关资源类型 Schema 和过滤接口已定义，但不能声称相应语料已覆盖。
- 当前重排为可解释的确定性启发式评分，不是训练过的 cross-encoder；没有真实教学效果指标。
- Tatoeba 已审核句子仍可能含语言或教学质量问题；教学使用前需要后续 Agent/Evaluator 检查上下文。
- 模型与索引缓存依赖本机路径，部署时应先运行下载和建索引脚本。
- 语料导入后必须运行建索引脚本发布新版本；在发布前运行中的进程继续使用旧的只读快照。各进程在其下一次 Workflow 请求时独立发现并加载新版本。
- 当前没有生产流量的缓存命中率、延迟与吞吐量测量；Redis 需要单独部署并配置合适的内存上限。高并发同键首次未命中时可能重复计算，本语料规模暂未引入分布式锁。
