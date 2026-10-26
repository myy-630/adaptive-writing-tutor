"""Run one real DeepSeek turn through the LangGraph HTTP workflow."""

from uuid import uuid4

from app.api.main import create_app
from app.core.config import Settings
from app.core.errors import ProviderUnavailable
from app.db.session import create_database_engine, create_session_factory
from app.domain.schemas import Student, WritingTask
from app.models import ToolCallRecordRow
from app.services.knowledge_graph.seed import seed_canonical_graph
from fastapi.testclient import TestClient
from sqlalchemy import func, select


def main() -> None:
    settings = Settings()
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
            result = response.json()
            after = client.get(f"/students/{student.id}/state").json()
        with sessions() as db:
            tool_calls = db.scalar(
                select(func.count(ToolCallRecordRow.id)).where(
                    ToolCallRecordRow.session_id == session_id
                )
            )
        print(
            {
                "stage": result["stage"],
                "mode": result["mode"],
                "evaluation_verdict": result["evaluation_verdict"],
                "blocked": result["blocked"],
                "teaching_excerpt": (result["teaching_text"] or "")[:300],
                "tool_calls": tool_calls,
                "student_state_unchanged": before == after,
            }
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
