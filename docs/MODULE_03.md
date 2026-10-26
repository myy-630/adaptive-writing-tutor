# 模块 3：Grammar Knowledge Graph

## 结构与职责

图谱只表示“学什么、知识之间是什么关系”，不存放教学材料，也不执行 RAG。节点涵盖语法四个一级领域、简单句五种结构、复杂句、词法及动词四个子领域、从句与连接、标点和书写规范。另有错误、句型、标志词和应用场景等辅助节点。

稳定节点 ID 由 `seed.py` 定义。当前种子包含 50 个节点、56 条关系。图谱关系为：

- `belongs_to`：子知识点 → 父知识点；
- `prerequisite_for`：前置知识 → 后续知识；
- `confused_with`：容易混淆的概念，按 ID 字典序只存一条，查询时视为双向；
- `common_error`：知识点 → 错误类型；
- `sentence_pattern`：知识点 → 句型；
- `common_marker`：知识点 → 标志词；
- `usable_for`：知识点 → 写作应用。

## 接口

- `seed_canonical_graph(sessions)`：幂等写入人工整理的图谱，不删除用户后加的节点和边。
- `GrammarKnowledgeGraph(sessions).get_node(id)`、`parent(id)`、`children(id)`、`prerequisites(id, transitive=...)`、`related_concepts(id)`、`link_error(error_code)`。
- `overlay(student_id, StudentStateReader)`：从模块 2 的统一只读接口取 mastery/confidence，并叠加在概念节点上。
- `validate()` / `assert_valid()`：检查必需节点、孤立节点、前置知识环、节点类型及关系方向。

查询从 PostgreSQL 载入 NetworkX 图后在内存运行。外部修改图谱后需显式 `refresh()`。

## 数据来源、外部依赖与限制

语法 taxonomy 与关系为项目内人工整理，未导入外部语料，不涉及第三方数据许可证。外部依赖为 PostgreSQL 与 NetworkX。错误映射目前基于稳定错误代码和别名；开放式错误文本由后续 Grammar Analyzer 先归类。节点规模适用于演示和课程规划，尚无大规模图库性能指标。
