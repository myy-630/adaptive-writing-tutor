from typing import Literal
from uuid import UUID

from app.agents.schemas import PlannerPlan
from app.agents.tool_runtime import AgentToolRuntime
from app.domain.enums import STAGE_ORDER, AbilityDimension, TeachingMode, TeachingStage
from app.domain.schemas import RetrievalResult
from app.services.grammar.schemas import GrammarAnalysis
from app.services.knowledge_graph.schemas import LearningPath
from app.services.student_state.schemas import StudentStateSnapshot

MODE_STRENGTH = {
    TeachingMode.INDEPENDENT: 0,
    TeachingMode.SEMI_GUIDED: 1,
    TeachingMode.GUIDED: 2,
}

STAGE_ABILITY = {
    TeachingStage.PROMPT_ANALYSIS: AbilityDimension.PROMPT_ANALYSIS,
    TeachingStage.GRAMMAR_REVISION: AbilityDimension.GRAMMAR,
    TeachingStage.STRUCTURE_REVISION: AbilityDimension.STRUCTURE,
    TeachingStage.CONTENT_EXPANSION: AbilityDimension.CONTENT,
    TeachingStage.LANGUAGE_REFINEMENT: AbilityDimension.SENTENCE_EXPRESSION,
}


class PlannerAgent:
    """Structured long-term learning planner; all mode and stage gates remain code."""

    def __init__(self, tools: AgentToolRuntime) -> None:
        self.tools = tools

    async def plan(
        self,
        *,
        student_id: UUID,
        session_id: UUID,
        stage: TeachingStage,
        mode: TeachingMode,
        stage_passed: bool,
    ) -> PlannerPlan:
        state = await self.tools.invoke(
            actor="planner",
            session_id=session_id,
            name="read_state",
            arguments={"student_id": student_id},
        )
        if not isinstance(state, StudentStateSnapshot):
            raise TypeError("read_state returned an unexpected result")
        next_stage = self._next_stage(stage) if stage_passed else stage
        selected_mode = self._mode(state)
        priority_node = (
            min(state.knowledge, key=lambda item: (item.mastery, item.node_id)).node_id
            if state.knowledge
            else None
        )
        target_node = priority_node if stage == TeachingStage.GRAMMAR_REVISION else None
        target_ability = (
            STAGE_ABILITY.get(stage)
            or min(
                state.abilities, key=lambda item: (item.rubric_score, item.dimension.value)
            ).dimension
        )
        path = await self._learning_path(session_id, student_id, target_node)
        prerequisite = path.next_node_id if path and path.next_node_id != target_node else None
        transfer_task_id = None
        if stage == TeachingStage.FINAL_EVALUATION and stage_passed:
            prompts = await self.tools.invoke(
                actor="planner",
                session_id=session_id,
                name="find_writing_prompts",
                arguments={"text": state.student.learning_goal, "top_k": 1},
            )
            if not isinstance(prompts, list) or not all(
                isinstance(item, RetrievalResult) for item in prompts
            ):
                raise TypeError("find_writing_prompts returned an unexpected result")
            if prompts:
                transfer_task_id = prompts[0].resource.id
        adjustment = self._scaffold_adjustment(mode, selected_mode)
        return PlannerPlan(
            stage=stage,
            next_stage=next_stage,
            mode=selected_mode,
            target_knowledge_node_id=target_node,
            long_term_priority_node_id=priority_node,
            target_ability_dimension=target_ability,
            prerequisite_node_id=prerequisite,
            learning_path=path,
            next_transfer_task_id=transfer_task_id,
            scaffold_adjustment=adjustment,
            rationale=(
                f"stage_passed={stage_passed}; weakest_ability={target_ability.value}; "
                f"long_term_priority={priority_node}; mode={selected_mode.value}; "
                f"prerequisite={prerequisite}"
            ),
        )

    async def _learning_path(
        self, session_id: UUID, student_id: UUID, target: str | None
    ) -> LearningPath | None:
        if target is None:
            return None
        path = await self.tools.invoke(
            actor="planner",
            session_id=session_id,
            name="plan_learning_path",
            arguments={"student_id": student_id, "goal_node_id": target},
        )
        if not isinstance(path, LearningPath):
            raise TypeError("plan_learning_path returned an unexpected result")
        return path

    async def incorporate_diagnosis(
        self,
        plan: PlannerPlan,
        analysis: GrammarAnalysis,
        *,
        student_id: UUID,
        session_id: UUID,
    ) -> PlannerPlan:
        """Prioritize a current writing error; retain long-term weakness as review."""
        if plan.stage != TeachingStage.GRAMMAR_REVISION or not analysis.errors:
            return plan
        target = analysis.errors[0].knowledge_node_id
        if plan.target_knowledge_node_id == target:
            return plan
        path = await self._learning_path(session_id, student_id, target)
        prerequisite = path.next_node_id if path and path.next_node_id != target else None
        return plan.model_copy(
            update={
                "target_knowledge_node_id": target,
                "prerequisite_node_id": prerequisite,
                "learning_path": path,
                "rationale": f"{plan.rationale}; observed_target={target}",
            }
        )

    @staticmethod
    def _next_stage(stage: TeachingStage) -> TeachingStage | None:
        index = STAGE_ORDER.index(stage)
        return STAGE_ORDER[index + 1] if index + 1 < len(STAGE_ORDER) else None

    @staticmethod
    def _mode(state: StudentStateSnapshot) -> TeachingMode:
        if all(item.evidence_count == 0 for item in state.abilities) and not state.knowledge:
            return TeachingMode.GUIDED
        if any(item.rubric_score < 0.4 for item in state.abilities) or any(
            item.mastery < 0.4 for item in state.knowledge
        ):
            return TeachingMode.GUIDED
        if state.prompt_dependency.average_hint_level >= 2:
            return TeachingMode.GUIDED
        if (
            all(item.rubric_score >= 0.75 for item in state.abilities)
            and state.prompt_dependency.independent_revision_count >= 3
            and state.prompt_dependency.average_hint_level <= 1
        ):
            return TeachingMode.INDEPENDENT
        return TeachingMode.SEMI_GUIDED

    @staticmethod
    def _scaffold_adjustment(
        previous: TeachingMode, current: TeachingMode
    ) -> Literal["increase", "decrease", "hold"]:
        difference = MODE_STRENGTH[current] - MODE_STRENGTH[previous]
        return "increase" if difference > 0 else "decrease" if difference < 0 else "hold"
