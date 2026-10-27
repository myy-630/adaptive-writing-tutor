from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.agents.evaluator import PedagogyEvaluator
from app.agents.planner import PlannerAgent
from app.agents.teaching import TeachingAgent
from app.agents.tool_runtime import build_agent_tools
from app.agents.tracing import ToolTraceStore
from app.core.config import Settings
from app.core.errors import DomainError
from app.domain.enums import TeachingMode, TeachingStage
from app.domain.schemas import Student, WritingTask
from app.models import (
    DraftRecord,
    StudentRecord,
    TeachingSessionRecord,
    WorkflowEventRecord,
    WritingTaskRecord,
)
from app.services.grammar.analyzer import GrammarAnalyzer
from app.services.knowledge_graph.graph import GrammarKnowledgeGraph
from app.services.knowledge_graph.path import GrammarLearningPathPlanner
from app.services.knowledge_graph.schemas import KnowledgeNode, NodeOverlay
from app.services.pedagogy.policy import PedagogyPolicy
from app.services.student_state.manager import StudentStateManager
from app.services.student_state.schemas import StudentStateSnapshot
from app.workflows.graph import WritingWorkflow
from app.workflows.schemas import (
    GrammarHint,
    KnowledgePath,
    SessionCreate,
    SessionView,
    WorkflowResult,
    WorkflowTurnInput,
)
from app.workflows.stage_gate import StageGate
from app.workflows.store import WorkflowStore

router = APIRouter()


def _sessions(request: Request) -> sessionmaker[Session]:
    return request.app.state.sessions


def _manager(request: Request) -> StudentStateManager:
    return StudentStateManager(_sessions(request), request.app.state.settings)


@router.post("/students", response_model=StudentStateSnapshot)
def create_student(student: Student, request: Request) -> StudentStateSnapshot:
    return _manager(request).initialize_student(student)


@router.get("/students/{student_id}/state", response_model=StudentStateSnapshot)
def student_state(student_id: UUID, request: Request) -> StudentStateSnapshot:
    return _manager(request).read_student_state(student_id)


@router.post("/tasks", response_model=WritingTask)
def create_task(task: WritingTask, request: Request) -> WritingTask:
    with _sessions(request).begin() as db:
        existing = db.get(WritingTaskRecord, task.id)
        if existing is not None:
            if (
                existing.prompt != task.prompt
                or existing.genre != task.genre
                or existing.grade != task.grade
                or existing.required_points != task.required_points
            ):
                raise DomainError("task_conflict", "Task ID already has different content", 409)
            return task
        db.add(
            WritingTaskRecord(
                id=task.id,
                prompt=task.prompt,
                genre=task.genre,
                grade=task.grade,
                required_points=task.required_points,
            )
        )
    return task


@router.post("/sessions", response_model=SessionView)
def create_session(data: SessionCreate, request: Request) -> SessionView:
    sessions = _sessions(request)
    with sessions.begin() as db:
        student = db.get(StudentRecord, data.student_id)
        task = db.get(WritingTaskRecord, data.task_id)
        if student is None or task is None:
            raise DomainError("session_owner_missing", "Student or task was not found", 404)
        if student.grade != task.grade:
            raise DomainError("grade_mismatch", "Task grade differs from student grade", 422)
        existing = db.get(TeachingSessionRecord, data.id)
        if existing is not None:
            if existing.student_id != data.student_id or existing.task_id != data.task_id:
                raise DomainError("session_conflict", "Session ID was already used", 409)
        else:
            db.add(
                TeachingSessionRecord(
                    id=data.id,
                    student_id=data.student_id,
                    task_id=data.task_id,
                    stage=TeachingStage.PROMPT_ANALYSIS,
                    mode=data.mode,
                )
            )
    _manager(request).set_current_session(data.student_id, data.id)
    return get_session(data.id, data.student_id, request)


@router.get("/sessions/{session_id}", response_model=SessionView)
def get_session(session_id: UUID, student_id: UUID, request: Request) -> SessionView:
    sessions = _sessions(request)
    with sessions() as db:
        session = db.get(TeachingSessionRecord, session_id)
        if session is None or session.student_id != student_id:
            raise DomainError("session_missing", "Teaching session was not found", 404)
        task = db.get(WritingTaskRecord, session.task_id)
        if task is None:
            raise DomainError("task_missing", "Writing task was not found", 404)
        draft = db.get(DraftRecord, session.current_draft_id) if session.current_draft_id else None
        latest = db.scalar(
            select(WorkflowEventRecord)
            .where(
                WorkflowEventRecord.session_id == session_id,
                WorkflowEventRecord.completed.is_(True),
            )
            .order_by(WorkflowEventRecord.created_at.desc(), WorkflowEventRecord.id.desc())
            .limit(1)
        )
        snapshot = _manager(request).read_student_state(student_id)
        hints, paths = (
            _grammar_workspace(sessions, student_id, draft.content, snapshot)
            if draft
            and session.stage == TeachingStage.GRAMMAR_REVISION
            and session.mode != TeachingMode.INDEPENDENT
            else ([], [])
        )
        view = SessionView(
            id=session.id,
            student_id=session.student_id,
            task=WritingTask(
                id=task.id,
                prompt=task.prompt,
                genre=task.genre,
                grade=task.grade,
                required_points=task.required_points,
            ),
            stage=session.stage,
            mode=session.mode,
            current_draft=draft.content if draft else None,
            completed=session.completed_at is not None,
            student_state=snapshot,
            last_result=(
                WorkflowResult.model_validate(latest.result)
                if latest and latest.result and session.mode != TeachingMode.INDEPENDENT
                else None
            ),
            grammar_hints=hints,
            knowledge_paths=paths,
        )
    return view


def _grammar_workspace(
    sessions: sessionmaker[Session],
    student_id: UUID,
    text: str,
    snapshot: StudentStateSnapshot,
) -> tuple[list[GrammarHint], list[KnowledgePath]]:
    graph = GrammarKnowledgeGraph(sessions)
    path_planner = GrammarLearningPathPlanner(graph)
    errors = GrammarAnalyzer(graph).analyze(text).errors
    hints = [
        GrammarHint(
            start_offset=issue.start_offset,
            end_offset=issue.end_offset,
            original_expression=issue.original_expression,
            category=issue.primary_category,
            knowledge_node_id=issue.knowledge_node_id,
        )
        for issue in errors
    ]
    mastery = {item.node_id: item for item in snapshot.knowledge}

    def overlay(node: KnowledgeNode) -> NodeOverlay:
        current = mastery.get(node.id)
        return NodeOverlay(
            student_id=student_id,
            node=node,
            mastery=current.mastery if current else None,
            confidence=current.confidence if current else None,
            evidence_count=current.evidence_count if current else 0,
        )

    paths = []
    for node_id in dict.fromkeys(issue.knowledge_node_id for issue in errors):
        node = graph.get_node(node_id)
        if node is not None:
            paths.append(
                KnowledgePath(
                    target=overlay(node),
                    prerequisites=[overlay(item) for item in graph.prerequisites(node_id)],
                    learning_path=path_planner.plan(node_id, snapshot),
                )
            )
    return hints, paths


@router.post("/sessions/{session_id}/turn", response_model=WorkflowResult)
async def workflow_turn(
    session_id: UUID, data: WorkflowTurnInput, request: Request
) -> WorkflowResult:
    settings: Settings = request.app.state.settings
    sessions = _sessions(request)
    manager = _manager(request)
    knowledge_graph = GrammarKnowledgeGraph(sessions)
    analyzer = GrammarAnalyzer(knowledge_graph)
    retriever = request.app.state.retrieval_runtime.current()
    trace_store = ToolTraceStore(sessions)
    tools = build_agent_tools(manager, knowledge_graph, retriever, trace_store.record)
    policy = PedagogyPolicy()
    provider = request.app.state.model_provider
    async with WritingWorkflow.postgres_checkpointer(settings) as saver:
        workflow = WritingWorkflow(
            store=WorkflowStore(
                sessions,
                manager,
                StageGate(analyzer, min_draft_words=settings.workflow_min_draft_words),
            ),
            manager=manager,
            planner=PlannerAgent(tools),
            analyzer=analyzer,
            policy=policy,
            teacher=TeachingAgent(provider, tools, policy),
            evaluator=PedagogyEvaluator(provider, policy),
            checkpointer=saver,
            max_regenerations=settings.workflow_max_regenerations,
        )
        return await workflow.run(
            session_id=session_id,
            student_id=data.student_id,
            submission=data.submission,
        )
