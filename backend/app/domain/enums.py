from enum import StrEnum


class TeachingStage(StrEnum):
    PROMPT_ANALYSIS = "prompt_analysis"
    FIRST_DRAFT = "first_draft"
    GRAMMAR_REVISION = "grammar_revision"
    STRUCTURE_REVISION = "structure_revision"
    CONTENT_EXPANSION = "content_expansion"
    LANGUAGE_REFINEMENT = "language_refinement"
    SECOND_DRAFT = "second_draft"
    FINAL_EVALUATION = "final_evaluation"


STAGE_ORDER: tuple[TeachingStage, ...] = tuple(TeachingStage)


class TeachingMode(StrEnum):
    GUIDED = "guided"
    SEMI_GUIDED = "semi_guided"
    INDEPENDENT = "independent"


class AbilityDimension(StrEnum):
    PROMPT_ANALYSIS = "prompt_analysis"
    STRUCTURE = "structure"
    CONTENT = "content"
    GRAMMAR = "grammar"
    SENTENCE_EXPRESSION = "sentence_expression"


class EvidenceOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    UNCERTAIN = "uncertain"


class PedagogyAction(StrEnum):
    SELF_CHECK = "self_check"
    LOCATION_HINT = "location_hint"
    CONCEPT_HINT = "concept_hint"
    SOCRATIC_QUESTION = "socratic_question"
    BREAK_DOWN = "break_down"
    CONTRAST_EXAMPLE = "contrast_example"
    KG_MICRO_LESSON = "kg_micro_lesson"
    LOCAL_DEMONSTRATION = "local_demonstration"
    DIRECT_EXPLANATION = "direct_explanation"
    TRANSFER_PRACTICE = "transfer_practice"
    INDEPENDENT_RETRY = "independent_retry"


class ResourceType(StrEnum):
    WRITING_PROMPT = "writing_prompt"
    STUDENT_ESSAY = "student_essay"
    MODEL_PARAGRAPH = "model_paragraph"
    GRAMMAR_ERROR = "grammar_error"
    HUMAN_CORRECTION = "human_correction"
    BASIC_SENTENCE = "basic_sentence"
    SENTENCE_TRANSFORMATION = "sentence_transformation"
    GRAMMAR_EXPLANATION = "grammar_explanation"
    STRUCTURE_EXAMPLE = "structure_example"
    TRANSFER_EXERCISE = "transfer_exercise"


class ResourceOrigin(StrEnum):
    HUMAN = "human"
    PUBLIC = "public"
    GENERATED = "generated"


class ToolCallStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    DEGRADED = "degraded"


class EvaluationVerdict(StrEnum):
    PASS = "pass"
    DIRECTIVE = "directive"
    BLOCK = "block"


class NodeKind(StrEnum):
    CONCEPT = "concept"
    ERROR = "error"
    PATTERN = "pattern"
    MARKER = "marker"
    APPLICATION = "application"


class EdgeRelation(StrEnum):
    BELONGS_TO = "belongs_to"
    PREREQUISITE_FOR = "prerequisite_for"
    CONFUSED_WITH = "confused_with"
    COMMON_ERROR = "common_error"
    SENTENCE_PATTERN = "sentence_pattern"
    COMMON_MARKER = "common_marker"
    USABLE_FOR = "usable_for"


class DiagnosticSeverity(StrEnum):
    MINOR = "minor"
    MODERATE = "moderate"
    MAJOR = "major"
