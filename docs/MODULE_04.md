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

Dense 模型由 FastEmbed 加载，其[模型卡](https://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q)标记为 MIT 许可。首次下载可能较慢；模型权重与 `.npz` 索引保存在本地 `data/indexes/` 并被 Git 忽略。索引元数据保存语料哈希、模型名、FastEmbed 版本、资源数和向量维度；加载时验证匹配，不匹配则要求重建。重建后向量和固定 Query Set 排序均通过回归测试。

## 核心接口

- `ResourceStore.import_jsonl` / `add_resources` / `list_resources`：元数据验证、入库和重复导入保护。
- `HybridRetriever.build_index` / `load_index` / `search(RetrievalQuery)`：索引构建和结构化 Top-K 检索。
- `HybridRetriever.find_writing_prompts`：供 Planner 搜索下一题。
- `HybridRetriever.find_teaching_material`：供 Teaching Agent 搜索例句、微课、结构案例及练习。
- `tests/fixtures/retrieval_queries.json`：固定回归查询。

Knowledge Graph 与 RAG 代码分离。检索资源可携带稳定知识点 ID 作过滤，但检索服务不执行图谱查询或学习路径决策。

## 已知限制

- 公开样本目前只有基础句子，尚未导入公开作文、人工纠错或错误案例；相关资源类型 Schema 和过滤接口已定义，但不能声称相应语料已覆盖。
- 当前重排为可解释的确定性启发式评分，不是训练过的 cross-encoder；没有真实教学效果指标。
- Tatoeba 已审核句子仍可能含语言或教学质量问题；教学使用前需要后续 Agent/Evaluator 检查上下文。
- 模型与索引缓存依赖本机路径，部署时应先运行下载和建索引脚本。
