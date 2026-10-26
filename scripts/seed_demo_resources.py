from uuid import NAMESPACE_URL, uuid5

from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.domain.enums import AbilityDimension, ResourceOrigin, ResourceType
from app.domain.schemas import RetrievalResource
from app.services.retrieval.store import ResourceStore

EXAMPLES = (
    (
        "email_school_day",
        ResourceType.WRITING_PROMPT,
        "Write an email to a friend about a memorable school day. "
        "Explain what happened and why it mattered.",
        "email",
        [],
        [AbilityDimension.CONTENT],
    ),
    (
        "narrative_challenge",
        ResourceType.WRITING_PROMPT,
        "Write a short narrative about a challenge you solved with a friend. "
        "Include details and your feelings.",
        "narrative",
        [],
        [AbilityDimension.CONTENT],
    ),
    (
        "simple_past_explanation",
        ResourceType.GRAMMAR_EXPLANATION,
        "Use the past form of a verb for a finished action at a known past time, "
        "such as yesterday.",
        None,
        ["simple_past"],
        [AbilityDimension.GRAMMAR],
    ),
    (
        "simple_past_transfer",
        ResourceType.TRANSFER_EXERCISE,
        "Change a present-tense sentence into the simple past, "
        "then write a new sentence about yesterday.",
        None,
        ["simple_past"],
        [AbilityDimension.GRAMMAR],
    ),
    (
        "paragraph_structure",
        ResourceType.STRUCTURE_EXAMPLE,
        "A clear paragraph begins with a topic sentence, follows with explanation "
        "and a specific example, and ends with a transition.",
        None,
        [],
        [AbilityDimension.STRUCTURE],
    ),
    (
        "because_transformation",
        ResourceType.SENTENCE_TRANSFORMATION,
        "Combine 'I stayed home' and 'It was raining' using because: "
        "I stayed home because it was raining.",
        None,
        ["logical_connection"],
        [AbilityDimension.SENTENCE_EXPRESSION],
    ),
)


def demo_resources() -> list[RetrievalResource]:
    resources = []
    for name, kind, content, genre, nodes, abilities in EXAMPLES:
        source = f"awt:demo:{name}"
        resources.append(
            RetrievalResource(
                id=uuid5(NAMESPACE_URL, source),
                content=content,
                resource_type=kind,
                grade=9,
                genre=genre,
                knowledge_node_ids=nodes,
                ability_dimensions=abilities,
                difficulty=0.4,
                language_level="A2-B1",
                source=source,
                dataset_id=source,
                license="Project-generated demo content",
                attribution="Adaptive Writing Tutor (AI-generated demo)",
                origin=ResourceOrigin.GENERATED,
                processing_notes="Authored for local retrieval demonstration; not benchmark data",
            )
        )
    return resources


def main() -> None:
    engine = create_database_engine(Settings())
    try:
        store = ResourceStore(create_session_factory(engine))
        inserted = store.add_resources(demo_resources())
        print(f"Imported {inserted} new project demo resources")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
