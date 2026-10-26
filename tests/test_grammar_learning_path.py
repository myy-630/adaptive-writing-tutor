"""Focused tests for prerequisite ordering and mastery hysteresis."""

import networkx as nx
import pytest
from app.core.errors import DomainError
from app.domain.enums import EdgeRelation, NodeKind
from app.domain.schemas import KnowledgeState, Student
from app.services.knowledge_graph.graph import GrammarKnowledgeGraph
from app.services.knowledge_graph.path import GrammarLearningPathPlanner
from app.services.knowledge_graph.schemas import KnowledgeNode
from app.services.student_state.path_mastery import PathMasteryRules
from app.services.student_state.schemas import (
    InteractionState,
    PromptDependency,
    StudentStateSnapshot,
)


def graph() -> GrammarKnowledgeGraph:
    result = object.__new__(GrammarKnowledgeGraph)
    result.nodes = {
        name: KnowledgeNode(id=name, label=name, kind=NodeKind.CONCEPT, description=name)
        for name in ("foundation", "middle", "goal", "review_foundation", "review_goal")
    }
    result.graph = nx.MultiDiGraph()
    result.graph.add_nodes_from(result.nodes)
    for source, target in (
        ("foundation", "middle"),
        ("middle", "goal"),
        ("review_foundation", "review_goal"),
    ):
        result.graph.add_edge(source, target, key=EdgeRelation.PREREQUISITE_FOR.value)
    return result


def state(*knowledge: KnowledgeState) -> StudentStateSnapshot:
    return StudentStateSnapshot(
        student=Student(grade=8, learning_goal="Improve grammar"),
        abilities=[],
        knowledge=list(knowledge),
        error_patterns=[],
        prompt_dependency=PromptDependency(
            evidence_count=0,
            average_hint_level=0,
            independent_revision_count=0,
            micro_lesson_count=0,
            post_lesson_success_count=0,
            transfer_success_count=0,
        ),
        interaction=InteractionState(
            session_id=None,
            task_id=None,
            stage=None,
            mode=None,
            consecutive_failures=0,
            current_hint_level=0,
            confusion_score=0,
        ),
    )


def knowledge(node_id: str, mastery: float, *, mastered: bool = False) -> KnowledgeState:
    return KnowledgeState(
        node_id=node_id,
        mastery=mastery,
        confidence=0.75,
        evidence_count=9,
        path_mastered=mastered,
        occurrence_count=9,
        independent_discovery_count=0,
        independent_revision_count=0,
        hint_level_total=0,
        micro_lesson_count=0,
        post_lesson_success_count=0,
        transfer_success_count=0,
        next_essay_recurrence_count=0,
    )


def test_path_orders_full_prerequisites_then_long_term_review() -> None:
    planner = GrammarLearningPathPlanner(graph())
    snapshot = state(
        knowledge("foundation", 0.73, mastered=True),
        knowledge("middle", 0.7),
        knowledge("review_goal", 0.3),
    )
    path = planner.plan("goal", snapshot)
    assert [step.node.id for step in path.steps] == [
        "foundation",
        "middle",
        "goal",
        "review_foundation",
        "review_goal",
    ]
    assert path.review_node_ids == ["review_goal"]
    assert path.next_node_id == "middle"
    assert [step.mastery_state for step in path.steps[:3]] == ["mastered", "verify", "learn"]
    assert path.steps[2].blocked_by_node_ids == ["middle"]
    assert path.steps[4].purpose == "review"


def test_mastery_gate_has_distinct_entry_and_exit_thresholds() -> None:
    rules = PathMasteryRules()
    qualifying = dict(
        confidence=0.75,
        independent_successes=2,
        transfer_successes=0,
        recent_failures=0,
    )
    assert rules.advance(was_mastered=False, mastery=0.82, **qualifying)
    assert rules.advance(was_mastered=True, mastery=0.7, **qualifying)
    assert not rules.advance(was_mastered=False, mastery=0.7, **qualifying)
    assert not rules.advance(was_mastered=True, mastery=0.6, **qualifying)
    assert not rules.advance(
        was_mastered=True, mastery=0.82, **(qualifying | {"recent_failures": 2})
    )
    assert rules.advance(
        was_mastered=False,
        mastery=0.82,
        **(qualifying | {"recent_failures": 2, "verified_after_failure": True}),
    )


def test_path_rejects_prerequisite_cycle() -> None:
    cycle = graph()
    cycle.graph.add_edge("goal", "foundation", key=EdgeRelation.PREREQUISITE_FOR.value)
    with pytest.raises(DomainError, match="cycle"):
        GrammarLearningPathPlanner(cycle).plan("goal", state())
