"""Dependency-aware grammar path planning with long-term review branches."""

from heapq import heappop, heappush
from typing import Literal

import networkx as nx
from app.core.errors import DomainError
from app.domain.enums import NodeKind
from app.services.knowledge_graph.graph import GrammarKnowledgeGraph
from app.services.knowledge_graph.schemas import LearningPath, LearningPathStep
from app.services.student_state.path_mastery import PathMasteryRules
from app.services.student_state.schemas import StudentStateSnapshot


class GrammarLearningPathPlanner:
    def __init__(
        self,
        graph: GrammarKnowledgeGraph,
        *,
        rules: PathMasteryRules | None = None,
        long_term_limit: int = 1,
    ) -> None:
        if long_term_limit < 0:
            raise ValueError("Long-term review limit cannot be negative")
        self.graph = graph
        self.rules = rules or PathMasteryRules()
        self.long_term_limit = long_term_limit

    def plan(self, goal_node_id: str, state: StudentStateSnapshot) -> LearningPath:
        goal = self.graph.get_node(goal_node_id)
        if goal is None:
            raise DomainError("knowledge_node_missing", "Learning goal does not exist", 404)
        if goal.kind != NodeKind.CONCEPT:
            raise DomainError("invalid_learning_goal", "Learning goal must be a concept", 422)

        dependency_graph = self.graph._prerequisite_graph()
        primary = nx.ancestors(dependency_graph, goal_node_id) | {goal_node_id}
        review_goals = self._long_term_goals(state, primary)
        closure = set(primary)
        for review_goal in review_goals:
            closure.update(nx.ancestors(dependency_graph, review_goal))
            closure.add(review_goal)
        if any(self.graph.nodes[node_id].kind != NodeKind.CONCEPT for node_id in closure):
            raise DomainError(
                "invalid_knowledge_graph", "Prerequisite path contains a non-concept", 500
            )
        subgraph = dependency_graph.subgraph(closure)
        ordered = self._order(subgraph, primary, state)

        knowledge = {item.node_id: item for item in state.knowledge}
        completed: dict[str, bool] = {}
        steps: list[LearningPathStep] = []
        for node_id in ordered:
            prerequisites = sorted(subgraph.predecessors(node_id))
            blocked_by = [item for item in prerequisites if not completed[item]]
            item = knowledge.get(node_id)
            mastery = item.mastery if item else None
            confidence = item.confidence if item else None
            mastery_state: Literal["learn", "verify", "mastered"]
            if item is None or item.mastery < self.rules.learn_below:
                mastery_state = "learn"
            elif item.path_mastered and item.mastery >= self.rules.exit_mastery:
                mastery_state = "mastered"
            else:
                mastery_state = "verify"
            done = mastery_state == "mastered" and not blocked_by
            completed[node_id] = done
            status: Literal["mastered", "ready", "blocked"]
            if done:
                status, reason = "mastered", "Mastery confirmed by independent evidence"
            elif blocked_by:
                status, reason = "blocked", "Complete prerequisite steps first"
            elif mastery_state == "learn":
                status, reason = "ready", "Learn this concept before advancing"
            else:
                status, reason = "ready", "Verify this concept with an independent attempt"
            steps.append(
                LearningPathStep(
                    node=self.graph.nodes[node_id],
                    prerequisite_node_ids=prerequisites,
                    mastery=mastery,
                    confidence=confidence,
                    status=status,
                    mastery_state=mastery_state,
                    purpose="current" if node_id in primary else "review",
                    blocked_by_node_ids=blocked_by,
                    reason=reason,
                )
            )
        next_step = next((step for step in steps if step.status == "ready"), None)
        return LearningPath(
            goal_node_id=goal_node_id,
            review_node_ids=review_goals,
            steps=steps,
            next_node_id=next_step.node.id if next_step else None,
            completed=all(completed.values()),
            mastery_threshold=self.rules.enter_mastery,
            exit_threshold=self.rules.exit_mastery,
            confidence_threshold=self.rules.confidence,
        )

    def _long_term_goals(self, state: StudentStateSnapshot, primary: set[str]) -> list[str]:
        candidates = [
            item
            for item in state.knowledge
            if item.node_id not in primary
            and (node := self.graph.get_node(item.node_id)) is not None
            and node.kind == NodeKind.CONCEPT
            and not item.path_mastered
            and (
                item.mastery < 0.6
                or state.recent_knowledge_failures.get(item.node_id, 0)
                >= self.rules.recent_failure_reopen_count
            )
        ]
        candidates.sort(
            key=lambda item: (
                -state.recent_knowledge_failures.get(item.node_id, 0),
                item.mastery,
                item.confidence,
                item.node_id,
            )
        )
        return [item.node_id for item in candidates[: self.long_term_limit]]

    @staticmethod
    def _order(subgraph: nx.DiGraph, primary: set[str], state: StudentStateSnapshot) -> list[str]:
        knowledge = {item.node_id: item for item in state.knowledge}
        remaining = dict(subgraph.in_degree())
        ready: list[tuple[int, float, int, str]] = []

        def push(node_id: str) -> None:
            item = knowledge.get(node_id)
            heappush(
                ready,
                (
                    0 if node_id in primary else 1,
                    item.mastery if item else 0.0,
                    -state.recent_knowledge_failures.get(node_id, 0),
                    node_id,
                ),
            )

        for node_id, count in remaining.items():
            if count == 0:
                push(node_id)
        ordered: list[str] = []
        while ready:
            _, _, _, node_id = heappop(ready)
            ordered.append(node_id)
            for successor in subgraph.successors(node_id):
                remaining[successor] -= 1
                if remaining[successor] == 0:
                    push(successor)
        if len(ordered) != len(remaining):
            raise DomainError("invalid_knowledge_graph", "Prerequisite path contains a cycle", 500)
        return ordered
