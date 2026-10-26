from dataclasses import dataclass


@dataclass(frozen=True)
class TransferExercise:
    prompt: str
    expected: str


EXERCISES: dict[str, TransferExercise] = {
    "subject_verb_agreement": TransferExercise(
        prompt="Correct this new sentence: He go to school.",
        expected="He goes to school.",
    ),
    "tense": TransferExercise(
        prompt="Correct this new sentence: Yesterday she go to school.",
        expected="Yesterday she went to school.",
    ),
    "article": TransferExercise(
        prompt="Correct this new sentence: I saw dog.",
        expected="I saw a dog.",
    ),
    "simple_sentence": TransferExercise(
        prompt="Correct this fragment: Because it rained.",
        expected="It rained.",
    ),
    "complex_sentence": TransferExercise(
        prompt="Correct this run-on: I like music I like art.",
        expected="I like music. I like art.",
    ),
}


def exercise_for(node_id: str | None) -> TransferExercise | None:
    return EXERCISES.get(node_id) if node_id else None


def transfer_succeeded(node_id: str | None, response: str | None) -> bool:
    exercise = exercise_for(node_id)
    if exercise is None or not response:
        return False

    def normalize(text: str) -> str:
        return " ".join(text.casefold().split())

    return normalize(response) == normalize(exercise.expected)
