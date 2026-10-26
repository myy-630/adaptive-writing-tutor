模块名称：Grammar Analyzer

一、已实现能力
- 保守规则语法诊断；无错误、单错误、多错误；时态、主谓一致、冠词、句子结构错误；稳定位置、结构、置信度和 KG node linking 的结构化输出。

二、核心新增/修改文件
- `backend/app/services/grammar/{analyzer,schemas}.py`、`backend/app/domain/enums.py`、`tests/test_module5_grammar_analyzer.py`、`scripts/demo_grammar_analyzer.py`、`docs/MODULE_05.md`、`README.md`。

三、核心接口
- `GrammarAnalyzer.analyze(text) -> GrammarAnalysis`；`GrammarError` 结构化内部诊断对象。

四、执行的检查与测试
- 模块 5 专项测试、真实 PostgreSQL KG 集成演示、Ruff、mypy、全量前置回归、职责边界及原始诊断 UI 暴露检查。

五、测试结果
- 8/8 模块 5 专项、44/44 前置回归，总计 52/52 通过。真实样例 `She go to school. I saw dog.` 返回两个按字符位置排序、分别映射 `subject_verb_agreement` 和 `article` 的诊断；无错误样例返回空列表。

六、发现并修复的问题
- 对删除句首从属连词的句子结构诊断，允许 `corrected_expression` 为空，但始终提供完整 `corrected_sentence`；将候选规则拆分为动词、冠词和句子结构三组，保持职责清晰。

七、已知限制
- 规则覆盖有限，不可声称具备通用语法检查器能力；结构标签为启发式结果；开放式复杂错误可能漏检。

八、回归结果
- 模块 1–4 共 44 项重要测试全部通过。

九、是否满足本模块验收标准
是

十、是否具备进入下一模块的条件
是
