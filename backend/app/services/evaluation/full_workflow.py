import asyncio
from uuid import uuid4

from app.api.main import create_app
from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.domain.enums import TeachingMode, TeachingStage
from app.models.tool_trace import ToolCallRecordRow
from app.services.evaluation.schemas import (
    EvaluationCase,
    ObservedToolCall,
    ResponseRecord,
    VariantName,
)
from fastapi.testclient import TestClient
from sqlalchemy import select


class FullWorkflowEvaluation:
    """Run the actual HTTP/LangGraph tutor path for one writing evaluation case."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(self, case: EvaluationCase) -> ResponseRecord:
        return await asyncio.to_thread(self._run_sync, case)

    def _run_sync(self, case: EvaluationCase) -> ResponseRecord:
        if case.student_id is None:
            raise ValueError("full workflow evaluation requires a persisted student")
        if case.stage != TeachingStage.GRAMMAR_REVISION or case.mode != TeachingMode.GUIDED:
            raise ValueError("full workflow evaluation currently supports guided grammar cases")
        task_id = uuid4()
        with TestClient(create_app(self.settings)) as client:
            task = client.post(
                "/tasks",
                json={
                    "id": str(task_id),
                    "prompt": case.task_prompt,
                    "genre": case.task_genre,
                    "grade": case.grade,
                    "required_points": case.required_points,
                },
            )
            self._require_ok(task.status_code, task.text)
            session = client.post(
                "/sessions",
                json={
                    "id": str(case.session_id),
                    "student_id": str(case.student_id),
                    "task_id": str(task_id),
                    "mode": case.mode.value,
                },
            )
            self._require_ok(session.status_code, session.text)
            self._turn(client, case, {"kind": "start"})
            self._turn(
                client,
                case,
                {
                    "kind": "response",
                    "prompt_analysis": {
                        "audience": "classmates",
                        "purpose": "describe a memorable day",
                        "genre": case.task_genre,
                        "required_points": case.required_points,
                        "tense": "past",
                        "person": "first",
                        "constraints": "stay on topic",
                    },
                },
            )
            result = self._turn(client, case, {"kind": "response", "text": case.student_text})
        if result["stage"] != case.stage.value:
            raise ValueError(f"full workflow stopped at unexpected stage: {result['stage']}")
        engine = create_database_engine(self.settings)
        try:
            sessions = create_session_factory(engine)
            with sessions() as db:
                traces = db.scalars(
                    select(ToolCallRecordRow)
                    .where(ToolCallRecordRow.session_id == case.session_id)
                    .order_by(ToolCallRecordRow.called_at, ToolCallRecordRow.id)
                ).all()
                tools = [ObservedToolCall(actor=row.actor, name=row.tool_name) for row in traces]
        finally:
            engine.dispose()
        return ResponseRecord(
            case_id=case.id,
            variant=VariantName.FULL_SYSTEM,
            text=result["teaching_text"],
            stage=case.stage,
            mode=case.mode,
            action=result["action"],
            tool_calls=tools,
            stage_history=[
                TeachingStage.PROMPT_ANALYSIS,
                TeachingStage.FIRST_DRAFT,
                TeachingStage.GRAMMAR_REVISION,
            ],
            evaluator_verdict=result["evaluation_verdict"],
            provider_model=(
                self.settings.deepseek_model
                if self.settings.model_provider == "deepseek"
                else self.settings.openai_model
            ),
        )

    @staticmethod
    def _require_ok(status: int, body: str) -> None:
        if status != 200:
            raise RuntimeError(f"workflow HTTP returned {status}: {body[:500]}")

    def _turn(self, client: TestClient, case: EvaluationCase, submission: dict) -> dict:
        response = client.post(
            f"/sessions/{case.session_id}/turn",
            json={
                "student_id": str(case.student_id),
                "submission": {**submission, "request_id": str(uuid4())},
            },
        )
        self._require_ok(response.status_code, response.text)
        return response.json()
