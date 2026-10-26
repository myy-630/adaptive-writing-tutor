"""Run a real state → diagnosis → policy decision against the local test database."""

from datetime import UTC, datetime
from uuid import uuid4

from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.domain import ErrorRecord, LearningEvidence, Student, TeachingMode, TeachingStage
from app.domain.enums import EvidenceOutcome
from app.models import TeachingSessionRecord, WritingTaskRecord
from app.services.grammar.analyzer import GrammarAnalyzer
from app.services.knowledge_graph.graph import GrammarKnowledgeGraph
from app.services.pedagogy.policy import PedagogyPolicy
from app.services.pedagogy.schemas import IntentLabel, PolicyContext, StudentIntent
from app.services.student_state.manager import StudentStateManager


def main() -> None:
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        sessions = create_session_factory(engine)
        diagnostic = (
            GrammarAnalyzer(GrammarKnowledgeGraph(sessions)).analyze("She go to school.").errors[0]
        )
        manager = StudentStateManager(sessions, settings)
        student = Student(grade=9, learning_goal="Practice English writing")
        manager.initialize_student(student)
        task_id, session_id = uuid4(), uuid4()
        with sessions.begin() as db:
            db.add(
                WritingTaskRecord(id=task_id, prompt="My school day", genre="narrative", grade=9)
            )
            db.flush()
            db.add(
                TeachingSessionRecord(
                    id=session_id,
                    student_id=student.id,
                    task_id=task_id,
                    stage=TeachingStage.GRAMMAR_REVISION,
                    mode=TeachingMode.GUIDED,
                )
            )
        for _ in range(2):
            manager.record_error(
                ErrorRecord(
                    student_id=student.id,
                    session_id=session_id,
                    category=diagnostic.primary_category,
                    knowledge_node_id=diagnostic.knowledge_node_id,
                    original_text=diagnostic.original_expression,
                    observed_at=datetime.now(UTC),
                )
            )
            manager.record_evidence(
                LearningEvidence(
                    student_id=student.id,
                    session_id=session_id,
                    knowledge_node_id=diagnostic.knowledge_node_id,
                    outcome=EvidenceOutcome.FAILURE,
                    observed_at=datetime.now(UTC),
                )
            )
        snapshot = manager.read_student_state(student.id)
        policy_input = PolicyContext.from_student_state(
            snapshot,
            stage=TeachingStage.GRAMMAR_REVISION,
            mode=TeachingMode.GUIDED,
            issue_type=diagnostic.primary_category,
            target_knowledge_node_id=diagnostic.knowledge_node_id,
            intent=StudentIntent(primary=IntentLabel.REQUEST_HELP),
            recent_error_recurrence=True,
        )
        decision = PedagogyPolicy().decide(policy_input)
        print(
            {
                "student_id": str(student.id),
                "database_error_count": snapshot.error_patterns[0].count,
                "consecutive_failures": snapshot.interaction.consecutive_failures,
                "diagnostic_node_id": diagnostic.knowledge_node_id,
                "selected_action": decision.action.value,
                "scaffold_level": decision.scaffold_level,
                "may_reveal_answer": decision.may_reveal_answer,
                "top_reason": decision.ranking[0].reasons,
            }
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
