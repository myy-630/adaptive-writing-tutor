from app.domain.enums import EdgeRelation, NodeKind
from app.models.knowledge_graph import KnowledgeEdgeRecord, KnowledgeNodeRecord
from app.services.knowledge_graph.schemas import KnowledgeEdge, KnowledgeNode
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

# Stable concept IDs are public identifiers consumed by Student State and Analyzer.
CONCEPTS: tuple[tuple[str, str, str | None, str], ...] = (
    ("grammar", "语法", None, "英语写作语法知识根节点"),
    ("sentence_structure", "句子结构", "grammar", "句子成分及组合方式"),
    ("simple_sentence", "简单句", "sentence_structure", "一个独立主谓结构"),
    ("subject_predicate", "主语 + 谓语", "simple_sentence", "基本主谓句式"),
    ("subject_verb_object", "主语 + 谓语 + 宾语", "simple_sentence", "及物动词宾语句式"),
    ("subject_linking_predicative", "主语 + 系动词 + 表语", "simple_sentence", "系表句式"),
    ("double_object", "主语 + 谓语 + 间接宾语 + 直接宾语", "simple_sentence", "双宾语句式"),
    ("object_complement", "主语 + 谓语 + 宾语 + 宾语补足语", "simple_sentence", "宾补句式"),
    ("complex_sentence", "复杂句", "sentence_structure", "由连接结构组合简单句"),
    ("combining_simple_sentences", "简单句组合", "complex_sentence", "通过逻辑关系连接简单句"),
    ("word_classes", "词法", "grammar", "词类及其语法形式"),
    ("verb", "动词", "word_classes", "表达动作或状态"),
    ("tense", "时态", "verb", "动作发生时间与体貌"),
    ("simple_past", "一般过去时", "tense", "过去已完成的动作或状态"),
    ("present_perfect", "现在完成时", "tense", "过去与现在关联的动作或状态"),
    ("subject_verb_agreement", "主谓一致", "verb", "主语与谓语在人称和数上一致"),
    ("passive_voice", "被动语态", "verb", "强调动作承受者"),
    ("non_finite_verb", "非谓语动词", "verb", "不作句子谓语的动词形式"),
    ("noun", "名词", "word_classes", "人事物或概念名称"),
    ("adjective", "形容词", "word_classes", "修饰名词或作表语"),
    ("adverb", "副词", "word_classes", "修饰动词、形容词或整句"),
    ("pronoun", "代词", "word_classes", "替代名词或名词短语"),
    ("preposition", "介词", "word_classes", "表示时间、地点或关系"),
    ("article", "冠词", "word_classes", "限定名词的特指或泛指"),
    ("clauses_connectors", "从句与连接", "grammar", "从句及逻辑连接结构"),
    ("noun_clause", "名词性从句", "clauses_connectors", "在句中承担名词作用的从句"),
    ("relative_clause", "定语从句", "clauses_connectors", "修饰名词的从句"),
    ("adverbial_clause", "状语从句", "clauses_connectors", "表达时间、原因、条件等关系"),
    ("conjunction", "连词", "clauses_connectors", "连接词、短语或分句"),
    ("logical_connection", "逻辑连接", "clauses_connectors", "表达因果、转折等句间关系"),
    ("punctuation_writing", "标点与书写规范", "grammar", "标点、大小写和拼写规则"),
    ("punctuation", "标点", "punctuation_writing", "句内及句末符号"),
    ("comma", "逗号", "punctuation", "分隔句内结构"),
    ("period", "句号", "punctuation", "结束陈述句"),
    ("capitalization", "大小写", "punctuation_writing", "句首及专有名词大写"),
    ("spelling", "拼写", "punctuation_writing", "词语字母拼写规范"),
)

CORE_REQUIRED_IDS = frozenset(item[0] for item in CONCEPTS)

OTHER_NODES: tuple[KnowledgeNode, ...] = (
    KnowledgeNode(
        id="error:sva",
        label="主谓不一致",
        kind=NodeKind.ERROR,
        description="主语与谓语数不一致",
        aliases=["sva", "subject_verb_agreement_error", "主谓不一致"],
    ),
    KnowledgeNode(
        id="error:tense",
        label="时态误用",
        kind=NodeKind.ERROR,
        description="动词时态与时间不匹配",
        aliases=["tense_error", "时态错误"],
    ),
    KnowledgeNode(
        id="error:article",
        label="冠词误用",
        kind=NodeKind.ERROR,
        description="冠词缺失或使用不当",
        aliases=["article_error", "冠词错误"],
    ),
    KnowledgeNode(
        id="error:fragment",
        label="句子残缺",
        kind=NodeKind.ERROR,
        description="缺少完整主谓结构",
        aliases=["fragment", "sentence_fragment"],
    ),
    KnowledgeNode(
        id="error:runon",
        label="句子粘连",
        kind=NodeKind.ERROR,
        description="独立分句连接不当",
        aliases=["run_on", "runon_sentence"],
    ),
    KnowledgeNode(
        id="error:comma_splice",
        label="逗号拼接",
        kind=NodeKind.ERROR,
        description="仅用逗号连接独立分句",
        aliases=["comma_splice"],
    ),
    KnowledgeNode(
        id="error:pronoun",
        label="代词误用",
        kind=NodeKind.ERROR,
        description="代词形式或指代不当",
        aliases=["pronoun_error"],
    ),
    KnowledgeNode(
        id="error:preposition",
        label="介词误用",
        kind=NodeKind.ERROR,
        description="介词搭配不当",
        aliases=["preposition_error"],
    ),
    KnowledgeNode(
        id="pattern:svo", label="S + V + O", kind=NodeKind.PATTERN, description="主谓宾基础句型"
    ),
    KnowledgeNode(
        id="pattern:passive",
        label="be + 过去分词",
        kind=NodeKind.PATTERN,
        description="常见被动语态结构",
    ),
    KnowledgeNode(
        id="marker:yesterday",
        label="yesterday",
        kind=NodeKind.MARKER,
        description="一般过去时常见标志词",
    ),
    KnowledgeNode(
        id="marker:since", label="since", kind=NodeKind.MARKER, description="现在完成时常见标志词"
    ),
    KnowledgeNode(
        id="application:narrative",
        label="记叙文",
        kind=NodeKind.APPLICATION,
        description="叙述过去经历的写作任务",
    ),
    KnowledgeNode(
        id="application:opinion",
        label="议论文",
        kind=NodeKind.APPLICATION,
        description="表达观点并论证的写作任务",
    ),
)

EXTRA_EDGES: tuple[tuple[str, str, EdgeRelation], ...] = (
    ("simple_sentence", "complex_sentence", EdgeRelation.PREREQUISITE_FOR),
    ("subject_predicate", "subject_verb_agreement", EdgeRelation.PREREQUISITE_FOR),
    ("verb", "tense", EdgeRelation.PREREQUISITE_FOR),
    ("tense", "passive_voice", EdgeRelation.PREREQUISITE_FOR),
    ("conjunction", "logical_connection", EdgeRelation.PREREQUISITE_FOR),
    ("simple_sentence", "clauses_connectors", EdgeRelation.PREREQUISITE_FOR),
    ("present_perfect", "simple_past", EdgeRelation.CONFUSED_WITH),
    ("subject_verb_agreement", "error:sva", EdgeRelation.COMMON_ERROR),
    ("tense", "error:tense", EdgeRelation.COMMON_ERROR),
    ("article", "error:article", EdgeRelation.COMMON_ERROR),
    ("simple_sentence", "error:fragment", EdgeRelation.COMMON_ERROR),
    ("complex_sentence", "error:runon", EdgeRelation.COMMON_ERROR),
    ("comma", "error:comma_splice", EdgeRelation.COMMON_ERROR),
    ("pronoun", "error:pronoun", EdgeRelation.COMMON_ERROR),
    ("preposition", "error:preposition", EdgeRelation.COMMON_ERROR),
    ("subject_verb_object", "pattern:svo", EdgeRelation.SENTENCE_PATTERN),
    ("passive_voice", "pattern:passive", EdgeRelation.SENTENCE_PATTERN),
    ("simple_past", "marker:yesterday", EdgeRelation.COMMON_MARKER),
    ("present_perfect", "marker:since", EdgeRelation.COMMON_MARKER),
    ("simple_past", "application:narrative", EdgeRelation.USABLE_FOR),
    ("logical_connection", "application:opinion", EdgeRelation.USABLE_FOR),
)


def canonical_nodes() -> list[KnowledgeNode]:
    return [
        KnowledgeNode(id=node_id, label=label, kind=NodeKind.CONCEPT, description=description)
        for node_id, label, _parent, description in CONCEPTS
    ] + list(OTHER_NODES)


def canonical_edges() -> list[KnowledgeEdge]:
    parent_edges = [
        KnowledgeEdge(source_id=node_id, target_id=parent, relation=EdgeRelation.BELONGS_TO)
        for node_id, _label, parent, _description in CONCEPTS
        if parent is not None
    ]
    return parent_edges + [
        KnowledgeEdge(source_id=source, target_id=target, relation=relation)
        for source, target, relation in EXTRA_EDGES
    ]


def seed_canonical_graph(sessions: sessionmaker[Session]) -> None:
    """Idempotently upsert curated grammar structure without deleting user additions."""
    with sessions.begin() as db:
        for node in canonical_nodes():
            values = node.model_dump()
            statement = insert(KnowledgeNodeRecord).values(**values)
            db.execute(
                statement.on_conflict_do_update(
                    index_elements=["id"],
                    set_={key: value for key, value in values.items() if key != "id"},
                )
            )
        for edge in canonical_edges():
            db.execute(
                insert(KnowledgeEdgeRecord)
                .values(**edge.model_dump())
                .on_conflict_do_nothing(index_elements=["source_id", "target_id", "relation"])
            )
