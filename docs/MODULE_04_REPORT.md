模块名称：RAG / Hybrid Retrieval

一、已实现能力
- 带来源/作者/许可元数据的公开句子导入、项目演示资源、BM25 与本地 dense 双路召回、RRF、元数据过滤、确定性重排、Top-K、固定查询回归与可复现索引。

二、核心新增/修改文件
- `data/processed/tatoeba_sample.jsonl`、`backend/app/services/retrieval/{store,hybrid,schemas}.py`、`backend/app/models/retrieval.py`、`backend/migrations/versions/bf4904baa42f_retrieval_resources.py`、`scripts/{fetch_tatoeba_sample,import_tatoeba_sample,seed_demo_resources,download_embedding_model,build_retrieval_index,demo_retrieval}.py`、`tests/test_module4_retrieval.py`、`tests/fixtures/retrieval_queries.json`、`docs/MODULE_04.md`、`README.md`。

三、核心接口
- `ResourceStore.import_jsonl` / `add_resources` / `list_resources`；`HybridRetriever.build_index` / `load_index` / `search` / `find_writing_prompts` / `find_teaching_material`；`RetrievalQuery` 与 `RetrievalResult`。

四、执行的检查与测试
- 官方 Tatoeba API 许可/作者字段核实；公开样本导入及二次导入；真实 FastEmbed ONNX 模型下载与本地索引；BM25/dense/RRF/filter/rerank 测试；固定查询、重建索引、空查询、无结果、非法元数据测试；Ruff、mypy、Alembic 漂移检查及全部前置回归。

五、测试结果
- 133 条公开句子和 6 条明确标记的项目演示资源入库；139 资源、384 维向量索引；9/9 模块 4 专项测试、35/35 前置模块回归，总计 44/44 通过。真实 dense 查询 `educational institution` 召回无同词重合的学校句子；真实语料的 rerank 改变了融合排序；迁移无漂移。

六、发现并修复的问题
- Python 系统证书未能验证官方 API，改用 `certifi` CA；首次官方 API 请求的 `sort=id` 不受支持，改用文档允许的 `sort=created`；模型下载权限审核曾超时，按提示重试后成功；补充真实语料重排顺序测试。

七、已知限制
- 公开语料当前只覆盖基础句子；演示资源不是 Benchmark；重排是启发式评分；Tatoeba 审核不等于教学质量保证；首次本地模型下载较慢，模型和索引缓存需在部署环境重建。

八、回归结果
- 模块 1 的 17 项、模块 2 的 11 项和模块 3 的 7 项重要测试全部通过。

九、是否满足本模块验收标准
是

十、是否具备进入下一模块的条件
是
