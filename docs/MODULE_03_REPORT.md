模块名称：Grammar Knowledge Graph

一、已实现能力
- 四大语法领域、简单句五种结构、词法/从句/标点节点；七种关系；父子/前置/相关/错误映射查询；Student State overlay；图谱完整性校验。

二、核心新增/修改文件
- `backend/app/services/knowledge_graph/{seed,graph,schemas}.py`、`backend/app/models/knowledge_graph.py`、`backend/migrations/versions/7639cff5624e_grammar_knowledge_graph.py`、`scripts/seed_grammar_graph.py`、`tests/test_module3_knowledge_graph.py`、`docs/MODULE_03.md`、`README.md`。

三、核心接口
- `seed_canonical_graph`；`GrammarKnowledgeGraph.get_node`、`parent`、`children`、`prerequisites`、`related_concepts`、`link_error`、`overlay`、`validate`、`assert_valid`。

四、执行的检查与测试
- 安装 NetworkX；执行 Alembic 迁移与漂移检查；真实 PostgreSQL 图谱播种并重复播种；模块 3 专项与模块 1–2 回归；Ruff、mypy；代码和职责边界检查。

五、测试结果
- 图谱实测 50 节点、56 边；无孤立节点、前置知识环、缺失核心节点或关系方向错误。7/7 模块 3 测试和 28/28 前置回归测试通过，总计 35/35；迁移无漂移。100 轮小规模查询在测试阈值 2 秒内完成。

六、发现并修复的问题
- 建模时发现模型与服务包可能循环导入，将图谱关系枚举移入公共 Domain 枚举。增加关系类型与方向校验测试。

七、已知限制
- 语义错误文本映射依赖后续 Analyzer 归类；图谱更新后需 `refresh()`；当前图谱规模仅按演示场景验收。

八、回归结果
- 模块 1 的 17 项与模块 2 的 11 项重要测试全部通过。

九、是否满足本模块验收标准
是

十、是否具备进入下一模块的条件
是
