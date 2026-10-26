"""Conservative mastery gate for grammar learning paths.

The BKT estimate measures knowledge; this gate also requires enough evidence from
unassisted work. A persisted mastered flag supplies hysteresis between updates.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PathMasteryRules:
    enter_mastery: float = 0.8
    exit_mastery: float = 0.65
    confidence: float = 0.5
    independent_successes: int = 2
    recent_failure_reopen_count: int = 2
    recent_window_days: int = 30
    learn_below: float = 0.4

    def __post_init__(self) -> None:
        if not 0 <= self.exit_mastery < self.enter_mastery <= 1:
            raise ValueError("Path mastery thresholds must satisfy 0 <= exit < enter <= 1")
        if not 0 <= self.confidence <= 1 or not 0 <= self.learn_below <= 1:
            raise ValueError("Path confidence and learning thresholds must be within 0..1")
        if (
            min(
                self.independent_successes,
                self.recent_failure_reopen_count,
                self.recent_window_days,
            )
            < 1
        ):
            raise ValueError("Path evidence counts and recent window must be positive")

    def advance(
        self,
        *,
        was_mastered: bool,
        mastery: float,
        confidence: float,
        independent_successes: int,
        transfer_successes: int,
        recent_failures: int,
        verified_after_failure: bool = False,
    ) -> bool:
        if recent_failures >= self.recent_failure_reopen_count and not verified_after_failure:
            return False
        if was_mastered:
            return mastery >= self.exit_mastery
        return (
            mastery >= self.enter_mastery
            and confidence >= self.confidence
            and (independent_successes >= self.independent_successes or transfer_successes >= 1)
        )
