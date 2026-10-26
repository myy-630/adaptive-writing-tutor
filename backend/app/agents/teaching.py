import json

from app.agents.prompts import TEACHING_SYSTEM
from app.agents.schemas import TeachingRequest, TeachingText, TeachingTurn
from app.agents.tool_runtime import AgentToolRuntime
from app.core.errors import DomainError
from app.core.provider import ModelProvider
from app.domain.enums import PedagogyAction, TeachingMode
from app.domain.schemas import RetrievalResult
from app.services.pedagogy.policy import PedagogyPolicy
from app.services.student_state.schemas import StudentStateSnapshot

MATERIAL_ACTIONS = {
    PedagogyAction.CONTRAST_EXAMPLE,
    PedagogyAction.KG_MICRO_LESSON,
    PedagogyAction.LOCAL_DEMONSTRATION,
    PedagogyAction.TRANSFER_PRACTICE,
}


class TeachingAgent:
    """Express an immutable policy decision in student-facing language."""

    def __init__(
        self, provider: ModelProvider, tools: AgentToolRuntime, policy: PedagogyPolicy
    ) -> None:
        self.provider = provider
        self.tools = tools
        self.policy = policy

    async def generate(self, request: TeachingRequest) -> TeachingTurn:
        self._validate_request(request)
        if request.plan.mode == TeachingMode.INDEPENDENT:
            return TeachingTurn(
                session_id=request.session_id,
                stage=request.plan.stage,
                mode=request.plan.mode,
                action=request.decision.action,
                target_knowledge_node_id=request.decision.target_knowledge_node_id,
            )
        state = await self.tools.invoke(
            actor="teaching",
            session_id=request.session_id,
            name="read_state",
            arguments={"student_id": request.student_id},
        )
        if not isinstance(state, StudentStateSnapshot):
            raise TypeError("read_state returned an unexpected result")
        materials = await self._materials(request)
        issue = request.issue.model_dump(mode="json") if request.issue else None
        if issue is not None and not request.decision.may_reveal_answer:
            issue.pop("corrected_expression")
            issue.pop("corrected_sentence")
        payload = {
            "stage": request.plan.stage.value,
            "mode": request.plan.mode.value,
            "learning_target": request.plan.target_knowledge_node_id,
            "action": request.decision.action.value,
            "scaffold_level": request.decision.scaffold_level,
            "may_reveal_answer": request.decision.may_reveal_answer,
            "needs_practice": request.decision.needs_practice,
            "practice_type": request.decision.practice_type,
            "pass_condition": request.decision.pass_condition,
            "student_goal": state.student.learning_goal,
            "student_grade": state.student.grade,
            "draft_text": request.draft_text,
            "issue": issue,
            "learning_path": (
                {
                    "goal_node_id": request.plan.learning_path.goal_node_id,
                    "next_node_id": request.plan.learning_path.next_node_id,
                    "steps": [
                        {"node_id": step.node.id, "label": step.node.label, "status": step.status}
                        for step in request.plan.learning_path.steps
                    ],
                }
                if request.plan.learning_path
                else None
            ),
            "materials": [
                {"id": str(item.resource.id), "content": item.resource.content}
                for item in materials
            ],
            "revision_directive": request.revision_directive,
            "transfer_prompt": request.transfer_prompt,
        }
        generated = await self.provider.generate_structured(
            system_prompt=TEACHING_SYSTEM,
            user_prompt=json.dumps(payload, ensure_ascii=False),
            response_type=TeachingText,
        )
        allowed_ids = {item.resource.id for item in materials}
        if any(resource_id not in allowed_ids for resource_id in generated.used_resource_ids):
            raise DomainError("unapproved_resource", "Teaching reply cited an unavailable resource")
        return TeachingTurn(
            session_id=request.session_id,
            stage=request.plan.stage,
            mode=request.plan.mode,
            action=request.decision.action,
            target_knowledge_node_id=request.decision.target_knowledge_node_id,
            text=generated.text,
            used_resource_ids=generated.used_resource_ids,
        )

    async def _materials(self, request: TeachingRequest) -> list[RetrievalResult]:
        if request.decision.action not in MATERIAL_ACTIONS:
            return []
        query = (
            request.issue.primary_category if request.issue else request.policy_context.issue_type
        )
        found = await self.tools.invoke(
            actor="teaching",
            session_id=request.session_id,
            name="find_teaching_material",
            arguments={
                "text": query,
                "knowledge_node_id": request.decision.target_knowledge_node_id,
                "top_k": 3,
            },
        )
        if not isinstance(found, list) or not all(
            isinstance(item, RetrievalResult) for item in found
        ):
            raise TypeError("find_teaching_material returned an unexpected result")
        return found

    def _validate_request(self, request: TeachingRequest) -> None:
        if request.plan.stage != request.policy_context.stage or request.plan.mode != (
            request.policy_context.mode
        ):
            raise DomainError("plan_mismatch", "Teaching request stage or mode differs from plan")
        if (
            request.plan.target_knowledge_node_id is not None
            and request.plan.target_knowledge_node_id != request.decision.target_knowledge_node_id
        ):
            raise DomainError("target_mismatch", "Teaching target differs from plan")
        if request.decision != self.policy.decide(request.policy_context):
            raise DomainError("policy_mismatch", "Teaching decision differs from policy")
