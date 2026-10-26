from app.core.config import Settings


def update_bkt(prior: float, success: bool, settings: Settings) -> float:
    """Bayesian observation update followed by a learning transition."""
    likelihood_known = 1 - settings.bkt_slip if success else settings.bkt_slip
    likelihood_unknown = settings.bkt_guess if success else 1 - settings.bkt_guess
    numerator = prior * likelihood_known
    denominator = numerator + (1 - prior) * likelihood_unknown
    posterior = prior if denominator == 0 else numerator / denominator
    return posterior + (1 - posterior) * settings.bkt_learn


def update_ability(previous: float, rubric_score: float, settings: Settings) -> float:
    return settings.ability_ema_alpha * rubric_score + (1 - settings.ability_ema_alpha) * previous


def evidence_confidence(count: int, settings: Settings) -> float:
    return count / (count + settings.confidence_prior_weight)
