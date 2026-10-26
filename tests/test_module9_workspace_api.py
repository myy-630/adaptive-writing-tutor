from uuid import uuid4

from app.agents.schemas import EvaluatorJudgement, TeachingText
from app.api.main import create_app
from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.services.knowledge_graph.seed import seed_canonical_graph
from fastapi.testclient import TestClient


class WorkspaceProvider:
    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_type: type
    ) -> object:
        if response_type is TeachingText:
            return TeachingText(text="Look at the target sentence and revise it yourself.")
        if response_type is EvaluatorJudgement:
            return EvaluatorJudgement(
                accurate_to_issue=True,
                scaffold_too_strong=False,
                scaffold_too_weak=False,
                actionable_next_step=True,
                stage_appropriate=True,
                ghostwriting=False,
                rationale="Appropriate guidance",
            )
        raise AssertionError(response_type)


INITIAL = (
    "She go to school every morning. I enjoy studying with my classmates after school. "
    "We discuss books and plan small projects together. "
    "Our teacher encourages us to share ideas clearly."
)


def _turn(client: TestClient, session_id: str, student_id: str, submission: dict) -> dict:
    response = client.post(
        f"/sessions/{session_id}/turn",
        json={"student_id": student_id, "submission": submission},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_grammar_workspace_is_live_and_sanitized() -> None:
    settings = Settings()
    engine = create_database_engine(settings)
    seed_canonical_graph(create_session_factory(engine))
    student_id, task_id, session_id = (str(uuid4()) for _ in range(3))
    try:
        with TestClient(create_app(settings, WorkspaceProvider())) as client:
            assert (
                client.post(
                    "/students",
                    json={"id": student_id, "grade": 9, "learning_goal": "Write clearly"},
                ).status_code
                == 200
            )
            assert (
                client.post(
                    "/tasks",
                    json={
                        "id": task_id,
                        "prompt": "Describe your school day",
                        "genre": "narrative",
                        "grade": 9,
                        "required_points": ["classes", "friends"],
                    },
                ).status_code
                == 200
            )
            assert (
                client.post(
                    "/sessions",
                    json={"id": session_id, "student_id": student_id, "task_id": task_id},
                ).status_code
                == 200
            )
            _turn(client, session_id, student_id, {"kind": "start"})
            _turn(
                client,
                session_id,
                student_id,
                {
                    "kind": "response",
                    "prompt_analysis": {
                        "audience": "classmates",
                        "purpose": "describe",
                        "genre": "narrative",
                        "required_points": ["classes", "friends"],
                        "tense": "present",
                        "person": "first",
                        "constraints": "stay on topic",
                    },
                },
            )
            result = _turn(client, session_id, student_id, {"kind": "response", "text": INITIAL})
            assert result["stage"] == "grammar_revision"
            response = client.get(f"/sessions/{session_id}", params={"student_id": student_id})
            assert response.status_code == 200
            view = response.json()
            assert view["current_draft"] == INITIAL
            assert view["student_state"]["student"]["id"] == student_id
            assert view["last_result"]["teaching_text"]
            assert view["grammar_hints"]
            assert view["knowledge_paths"]
            assert all("corrected_expression" not in hint for hint in view["grammar_hints"])
            assert all("suggested_revision" not in hint for hint in view["grammar_hints"])
    finally:
        engine.dispose()


def test_independent_workspace_exposes_no_guidance() -> None:
    settings = Settings()
    engine = create_database_engine(settings)
    student_id, task_id, session_id = (str(uuid4()) for _ in range(3))
    try:
        with TestClient(create_app(settings, WorkspaceProvider())) as client:
            client.post(
                "/students",
                json={"id": student_id, "grade": 9, "learning_goal": "Write independently"},
            )
            client.post(
                "/tasks",
                json={
                    "id": task_id,
                    "prompt": "Describe your day",
                    "genre": "narrative",
                    "grade": 9,
                },
            )
            client.post(
                "/sessions",
                json={
                    "id": session_id,
                    "student_id": student_id,
                    "task_id": task_id,
                    "mode": "independent",
                },
            )
            view = client.get(f"/sessions/{session_id}", params={"student_id": student_id})
            assert view.status_code == 200
            assert view.json()["last_result"] is None
            assert view.json()["grammar_hints"] == []
            assert view.json()["knowledge_paths"] == []
    finally:
        engine.dispose()
