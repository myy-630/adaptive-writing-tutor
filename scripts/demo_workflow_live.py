"""Run real DeepSeek turns and verify prompt-rubric Student State updates."""

from uuid import uuid4

from app.api.main import create_app
from app.core.config import Settings
from app.core.errors import ProviderUnavailable
from app.db.session import create_database_engine, create_session_factory
from app.domain.schemas import Student, WritingTask
from app.models import ToolCallRecordRow, WorkflowEventRecord
from app.services.knowledge_graph.seed import seed_canonical_graph
from fastapi.testclient import TestClient
from sqlalchemy import func, select


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    if settings.model_provider != "deepseek" or not settings.deepseek_api_key:
        raise ProviderUnavailable()
    engine = create_database_engine(settings)
    try:
        sessions = create_session_factory(engine)
        seed_canonical_graph(sessions)
        student = Student(grade=9, learning_goal="Improve English school writing")
        task = WritingTask(
            prompt="Describe a school day to a friend.",
            genre="narrative",
            grade=9,
            required_points=["classes", "friends"],
        )
        session_id = uuid4()
        with TestClient(create_app(settings)) as client:
            assert client.post("/students", json=student.model_dump(mode="json")).status_code == 200
            assert client.post("/tasks", json=task.model_dump(mode="json")).status_code == 200
            created = client.post(
                "/sessions",
                json={
                    "id": str(session_id),
                    "student_id": str(student.id),
                    "task_id": str(task.id),
                },
            )
            assert created.status_code == 200
            before = client.get(f"/students/{student.id}/state").json()
            response = client.post(
                f"/sessions/{session_id}/turn",
                json={
                    "student_id": str(student.id),
                    "submission": {"kind": "start", "request_id": str(uuid4())},
                },
            )
            response.raise_for_status()
            start_result = response.json()
            after_start = client.get(f"/students/{student.id}/state").json()
            prompt_response = client.post(
                f"/sessions/{session_id}/turn",
                json={
                    "student_id": str(student.id),
                    "submission": {
                        "kind": "response",
                        "request_id": str(uuid4()),
                        "prompt_analysis": {
                            "audience": "a friend who has never visited my school",
                            "purpose": "describe the classes and friendships in my school day",
                            "genre": "narrative",
                            "required_points": ["classes", "friends"],
                            "tense": "present",
                            "person": "first",
                            "constraints": (
                                "show specific moments from classes and time with friends"
                            ),
                        },
                    },
                },
            )
            prompt_response.raise_for_status()
            prompt_result = prompt_response.json()
            after_prompt = client.get(f"/students/{student.id}/state").json()
        with sessions() as db:
            tool_calls = db.scalar(
                select(func.count(ToolCallRecordRow.id)).where(
                    ToolCallRecordRow.session_id == session_id
                )
            )
            prompt_event = db.scalar(
                select(WorkflowEventRecord).where(
                    WorkflowEventRecord.session_id == session_id,
                    WorkflowEventRecord.stage_before == "prompt_analysis",
                    WorkflowEventRecord.payload["kind"].as_string() == "response",
                )
            )
            assert prompt_event is not None and prompt_event.stage_outcome is not None
            rubric = prompt_event.stage_outcome["rubric"]
        prompt_ability = next(
            ability
            for ability in after_prompt["abilities"]
            if ability["dimension"] == "prompt_analysis"
        )
        initial_prompt_ability = next(
            ability for ability in before["abilities"] if ability["dimension"] == "prompt_analysis"
        )
        assert before == after_start
        assert rubric is not None and prompt_ability["evidence_count"] == 1
        assert prompt_ability["rubric_score"] != initial_prompt_ability["rubric_score"]
        print(
            {
                "start_stage": start_result["stage"],
                "prompt_stage": prompt_result["stage"],
                "mode": prompt_result["mode"],
                "evaluation_verdict": prompt_result["evaluation_verdict"],
                "blocked": prompt_result["blocked"],
                "rubric": rubric,
                "prompt_ability": {
                    "score": prompt_ability["rubric_score"],
                    "evidence_count": prompt_ability["evidence_count"],
                },
                "tool_calls": tool_calls,
            }
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
