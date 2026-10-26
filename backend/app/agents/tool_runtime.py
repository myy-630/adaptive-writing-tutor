import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import UUID

from app.core.errors import DomainError
from app.domain.enums import ResourceType, ToolCallStatus
from app.domain.schemas import ToolCallRecord
from app.services.knowledge_graph.graph import GrammarKnowledgeGraph
from app.services.knowledge_graph.path import GrammarLearningPathPlanner
from app.services.retrieval.hybrid import HybridRetriever
from app.services.retrieval.schemas import RetrievalQuery
from app.services.student_state.manager import StudentStateReader
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadStateArgs(ToolArgs):
    student_id: UUID


class NodeArgs(ToolArgs):
    node_id: str = Field(min_length=1)


class LearningPathArgs(ToolArgs):
    student_id: UUID
    goal_node_id: str = Field(min_length=1)


class SearchArgs(ToolArgs):
    text: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)
    knowledge_node_id: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    actors: frozenset[str]
    args_type: type[ToolArgs]
    handler: Callable[[Any], object]
    fallback: Callable[[Any], object] | None = None
    timeout_seconds: float = 5.0
    retries: int = 1


@dataclass
class AgentToolRuntime:
    tools: dict[str, ToolSpec] = field(default_factory=dict)
    trace: list[ToolCallRecord] = field(default_factory=list)
    recorder: Callable[[ToolCallRecord], None] | None = None

    def register(self, name: str, spec: ToolSpec) -> None:
        if not name or name in self.tools or not spec.actors:
            raise ValueError("Tool name must be unique and actors must be nonempty")
        if spec.timeout_seconds <= 0 or spec.retries < 0:
            raise ValueError("Tool timeout and retries are invalid")
        self.tools[name] = spec

    async def invoke(
        self, *, actor: str, session_id: UUID, name: str, arguments: dict[str, object]
    ) -> object:
        started = monotonic()
        spec = self.tools.get(name)
        if spec is None or actor not in spec.actors:
            self._record(
                actor,
                session_id,
                name,
                ToolArgs(),
                ToolCallStatus.FAILURE,
                started,
                error_code="tool_forbidden",
            )
            raise DomainError("tool_forbidden", f"{actor} cannot call {name}", 403)
        try:
            parsed = spec.args_type.model_validate(arguments)
        except ValidationError:
            self._record(
                actor,
                session_id,
                name,
                ToolArgs(),
                ToolCallStatus.FAILURE,
                started,
                error_code="invalid_arguments",
            )
            raise
        last_error: Exception | None = None
        for _ in range(spec.retries + 1):
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(spec.handler, parsed), timeout=spec.timeout_seconds
                )
                self._record(actor, session_id, name, parsed, ToolCallStatus.SUCCESS, started)
                return result
            except Exception as exc:
                last_error = exc
                logger.warning("tool call failed: actor=%s tool=%s error=%s", actor, name, exc)
        if spec.fallback is not None:
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(spec.fallback, parsed), timeout=spec.timeout_seconds
                )
                self._record(actor, session_id, name, parsed, ToolCallStatus.DEGRADED, started)
                return result
            except Exception as exc:
                last_error = exc
        self._record(
            actor,
            session_id,
            name,
            parsed,
            ToolCallStatus.FAILURE,
            started,
            error_code=type(last_error).__name__ if last_error else "unknown",
        )
        raise DomainError("tool_failed", f"Tool {name} failed", 503) from last_error

    def _record(
        self,
        actor: str,
        session_id: UUID,
        name: str,
        arguments: ToolArgs,
        status: ToolCallStatus,
        started: float,
        error_code: str | None = None,
    ) -> None:
        record = ToolCallRecord(
            session_id=session_id,
            actor=actor,
            tool_name=name,
            arguments=arguments.model_dump(mode="json"),
            status=status,
            duration_ms=int((monotonic() - started) * 1000),
            error_code=error_code,
            called_at=datetime.now(UTC),
        )
        self.trace.append(record)
        if self.recorder is not None:
            self.recorder(record)


def build_agent_tools(
    reader: StudentStateReader,
    graph: GrammarKnowledgeGraph,
    retriever: HybridRetriever,
    recorder: Callable[[ToolCallRecord], None] | None = None,
) -> AgentToolRuntime:
    runtime = AgentToolRuntime(recorder=recorder)
    runtime.register(
        "read_state",
        ToolSpec(
            actors=frozenset({"planner", "teaching"}),
            args_type=ReadStateArgs,
            handler=lambda args: reader.read_student_state(args.student_id),
        ),
    )
    runtime.register(
        "prerequisites",
        ToolSpec(
            actors=frozenset({"planner", "teaching"}),
            args_type=NodeArgs,
            handler=lambda args: graph.prerequisites(args.node_id),
            fallback=lambda _args: [],
        ),
    )
    path_planner = GrammarLearningPathPlanner(graph)
    runtime.register(
        "plan_learning_path",
        ToolSpec(
            actors=frozenset({"planner"}),
            args_type=LearningPathArgs,
            handler=lambda args: path_planner.plan(
                args.goal_node_id, reader.read_student_state(args.student_id)
            ),
        ),
    )
    runtime.register(
        "find_teaching_material",
        ToolSpec(
            actors=frozenset({"planner", "teaching"}),
            args_type=SearchArgs,
            handler=lambda args: retriever.search(
                RetrievalQuery(
                    text=args.text,
                    top_k=args.top_k,
                    knowledge_node_id=args.knowledge_node_id,
                    resource_types=[
                        ResourceType.BASIC_SENTENCE,
                        ResourceType.GRAMMAR_EXPLANATION,
                        ResourceType.GRAMMAR_ERROR,
                        ResourceType.SENTENCE_TRANSFORMATION,
                        ResourceType.STRUCTURE_EXAMPLE,
                        ResourceType.TRANSFER_EXERCISE,
                    ],
                )
            ),
            fallback=lambda _args: [],
        ),
    )
    runtime.register(
        "find_writing_prompts",
        ToolSpec(
            actors=frozenset({"planner"}),
            args_type=SearchArgs,
            handler=lambda args: retriever.find_writing_prompts(args.text, args.top_k),
            fallback=lambda _args: [],
        ),
    )
    return runtime
