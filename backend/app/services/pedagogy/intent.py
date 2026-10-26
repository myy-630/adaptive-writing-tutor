import re

from app.services.pedagogy.schemas import IntentLabel, StudentIntent


def recognize_student_intent(message: str | None) -> StudentIntent:
    """Conservative multi-label signal extraction from a student's help message."""
    if not message:
        return StudentIntent(primary=IntentLabel.ATTEMPT)
    normalized = message.casefold()
    wants_answer = bool(
        re.search(r"直接告诉|给我答案|直接给|tell me the answer|just give me", normalized)
    )
    confused = bool(re.search(r"不懂|不会|搞不清|don't understand|confused|stuck", normalized))
    frustrated = bool(re.search(r"烦|崩溃|算了|frustrated|give up", normalized))
    asks_help = bool(re.search(r"帮|提示|help|hint|explain", normalized)) or confused
    primary = IntentLabel.REQUEST_HELP if asks_help else IntentLabel.ATTEMPT
    if wants_answer and not asks_help:
        primary = IntentLabel.REQUEST_ANSWER
    secondary = (
        [IntentLabel.REQUEST_ANSWER]
        if wants_answer and primary != IntentLabel.REQUEST_ANSWER
        else []
    )
    if confused and primary != IntentLabel.EXPRESS_CONFUSION:
        secondary.append(IntentLabel.EXPRESS_CONFUSION)
    return StudentIntent(
        primary=primary,
        secondary=secondary,
        confusion=0.7 if confused else 0,
        frustration=0.6 if frustrated else 0,
        requests_direct_answer=wants_answer,
    )
