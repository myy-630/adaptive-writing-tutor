from uuid import UUID

import networkx as nx
from app.core.errors import DomainError
from app.domain.enums import EdgeRelation, NodeKind
from app.models.knowledge_graph import KnowledgeEdgeRecord, KnowledgeNodeRecord
from app.services.knowledge_graph.schemas import GraphValidation, KnowledgeNode, NodeOverlay
from app.services.knowledge_graph.seed import CORE_REQUIRED_IDS
from app.services.student_state.manager import StudentStateReader
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class GrammarKnowledgeGraph:
    """Read-only graph queries over curated PostgreSQL nodes and relationships."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions
        self.refresh()

    def refresh(self) -> None:
        with self.sessions() as db:
            node_rows = db.scalars(select(KnowledgeNodeRecord)).all()
            edge_rows = db.scalars(select(KnowledgeEdgeRecord)).all()
        self.nodes = {
            row.id: KnowledgeNode(
                id=row.id,
                label=row.label,
                kind=row.kind,
                description=row.description,
                aliases=row.aliases,
            )
            for row in node_rows
        }
        self.graph = nx.MultiDiGraph()
        self.graph.add_nodes_from(self.nodes)
        for row in edge_rows:
            self.graph.add_edge(row.source_id, row.target_id, key=row.relation.value)
        self.error_aliases: dict[str, str] = {}
        for node in self.nodes.values():
            if node.kind == NodeKind.ERROR:
                for alias in [node.id, *node.aliases]:
                    self.error_aliases[alias.strip().casefold()] = node.id

    def get_node(self, node_id: str) -> KnowledgeNode | None:
        return self.nodes.get(node_id)

    def parent(self, node_id: str) -> KnowledgeNode | None:
        if node_id not in self.nodes:
            return None
        parent_ids = [
            target
            for _, target, relation in self.graph.out_edges(node_id, keys=True)
            if relation == EdgeRelation.BELONGS_TO.value
        ]
        return self.nodes[sorted(parent_ids)[0]] if parent_ids else None

    def children(self, node_id: str) -> list[KnowledgeNode]:
        if node_id not in self.nodes:
            return []
        child_ids = {
            source
            for source, _, relation in self.graph.in_edges(node_id, keys=True)
            if relation == EdgeRelation.BELONGS_TO.value
        }
        return [self.nodes[item] for item in sorted(child_ids)]

    def prerequisites(self, node_id: str, *, transitive: bool = False) -> list[KnowledgeNode]:
        if node_id not in self.nodes:
            return []
        prerequisite_graph = self._prerequisite_graph()
        ids = (
            nx.ancestors(prerequisite_graph, node_id)
            if transitive
            else set(prerequisite_graph.predecessors(node_id))
        )
        return [self.nodes[item] for item in sorted(ids)]

    def related_concepts(self, node_id: str) -> list[KnowledgeNode]:
        node = self.nodes.get(node_id)
        if node is None or node.kind != NodeKind.CONCEPT:
            return []
        related = set(self.graph.predecessors(node_id)) | set(self.graph.successors(node_id))
        related.discard(node_id)
        return [
            self.nodes[item]
            for item in sorted(related)
            if self.nodes[item].kind == NodeKind.CONCEPT
        ]

    def link_error(self, error_code: str) -> KnowledgeNode | None:
        error_id = self.error_aliases.get(error_code.strip().casefold())
        if error_id is None:
            return None
        concept_ids = [
            source
            for source, _, relation in self.graph.in_edges(error_id, keys=True)
            if relation == EdgeRelation.COMMON_ERROR.value
        ]
        return self.nodes[sorted(concept_ids)[0]] if concept_ids else None

    def overlay(self, student_id: UUID, reader: StudentStateReader) -> list[NodeOverlay]:
        student_state = reader.read_student_state(student_id)
        mastery = {item.node_id: item for item in student_state.knowledge}
        return [
            NodeOverlay(
                student_id=student_id,
                node=node,
                mastery=mastery[node.id].mastery if node.id in mastery else None,
                confidence=mastery[node.id].confidence if node.id in mastery else None,
                evidence_count=mastery[node.id].evidence_count if node.id in mastery else 0,
            )
            for node in sorted(self.nodes.values(), key=lambda item: item.id)
            if node.kind == NodeKind.CONCEPT
        ]

    def validate(self) -> GraphValidation:
        isolated = sorted(node_id for node_id in self.nodes if self.graph.degree(node_id) == 0)
        prerequisite_graph = self._prerequisite_graph()
        cycles = sorted({node for cycle in nx.simple_cycles(prerequisite_graph) for node in cycle})
        invalid: list[str] = []
        parent_count = {node_id: 0 for node_id in self.nodes}
        target_kind = {
            EdgeRelation.COMMON_ERROR: NodeKind.ERROR,
            EdgeRelation.SENTENCE_PATTERN: NodeKind.PATTERN,
            EdgeRelation.COMMON_MARKER: NodeKind.MARKER,
            EdgeRelation.USABLE_FOR: NodeKind.APPLICATION,
        }
        for source, target, relation_value in self.graph.edges(keys=True):
            relation = EdgeRelation(relation_value)
            source_node, target_node = self.nodes[source], self.nodes[target]
            if source == target:
                invalid.append(f"self-loop:{source}:{relation.value}")
            if relation == EdgeRelation.BELONGS_TO:
                parent_count[source] += 1
                if source_node.kind != NodeKind.CONCEPT or target_node.kind != NodeKind.CONCEPT:
                    invalid.append(f"belongs-direction:{source}:{target}")
            elif relation in {EdgeRelation.PREREQUISITE_FOR, EdgeRelation.CONFUSED_WITH}:
                if source_node.kind != NodeKind.CONCEPT or target_node.kind != NodeKind.CONCEPT:
                    invalid.append(f"concept-relation:{source}:{target}")
                if relation == EdgeRelation.CONFUSED_WITH and source >= target:
                    invalid.append(f"confusion-order:{source}:{target}")
            elif source_node.kind != NodeKind.CONCEPT or target_node.kind != target_kind[relation]:
                invalid.append(f"auxiliary-direction:{source}:{target}:{relation.value}")
        for node_id, node in self.nodes.items():
            if node.kind == NodeKind.CONCEPT:
                expected = 0 if node_id == "grammar" else 1
                if parent_count[node_id] != expected:
                    invalid.append(f"parent-count:{node_id}:{parent_count[node_id]}")
        return GraphValidation(
            node_count=len(self.nodes),
            edge_count=self.graph.number_of_edges(),
            isolated_node_ids=isolated,
            prerequisite_cycle_ids=cycles,
            missing_core_node_ids=sorted(CORE_REQUIRED_IDS - self.nodes.keys()),
            invalid_relationships=sorted(invalid),
        )

    def assert_valid(self) -> GraphValidation:
        result = self.validate()
        if (
            result.isolated_node_ids
            or result.prerequisite_cycle_ids
            or result.missing_core_node_ids
            or result.invalid_relationships
        ):
            raise DomainError("invalid_knowledge_graph", "Grammar graph validation failed", 500)
        return result

    def _prerequisite_graph(self) -> nx.DiGraph:
        graph = nx.DiGraph()
        graph.add_nodes_from(self.nodes)
        graph.add_edges_from(
            (source, target)
            for source, target, relation in self.graph.edges(keys=True)
            if relation == EdgeRelation.PREREQUISITE_FOR.value
        )
        return graph
