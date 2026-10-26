from collections import Counter

from app.domain.schemas import DomainModel
from app.services.grammar.analyzer import GrammarAnalyzer


class DraftComparison(DomainModel):
    resolved: dict[str, int]
    repeated: dict[str, int]
    new: dict[str, int]
    remaining_count: int

    def feedback(self) -> str:
        def render(items: dict[str, int]) -> str:
            return ", ".join(f"{name} ×{count}" for name, count in sorted(items.items())) or "none"

        return (
            "Detected grammar changes from Draft 1 to Draft 2: "
            f"resolved {render(self.resolved)}; repeated {render(self.repeated)}; "
            f"new {render(self.new)}. "
            "Use this as a revision checklist; it covers only patterns recognized by the analyzer."
        )


def compare_drafts(analyzer: GrammarAnalyzer, first: str, second: str) -> DraftComparison:
    before = Counter(error.knowledge_node_id for error in analyzer.analyze(first).errors)
    after = Counter(error.knowledge_node_id for error in analyzer.analyze(second).errors)
    repeated = before & after
    return DraftComparison(
        resolved=dict(before - repeated),
        repeated=dict(repeated),
        new=dict(after - repeated),
        remaining_count=sum(after.values()),
    )
