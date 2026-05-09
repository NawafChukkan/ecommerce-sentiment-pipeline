from __future__ import annotations


STAGE_SEQUENCE = ("introduction", "growth", "maturity", "decline")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def derive_generation_stage(age_ratio: float) -> str:
    if age_ratio < 0.20:
        return "introduction"
    if age_ratio < 0.46:
        return "growth"
    if age_ratio < 0.82:
        return "maturity"
    return "decline"


def classify_lifecycle_stage(
    age_ratio: float | None,
    revenue_change: float | None,
    sentiment_score: float | None,
    sell_through: float | None,
) -> str:
    age_ratio = 0.0 if age_ratio is None else age_ratio
    revenue_change = 0.0 if revenue_change is None else revenue_change
    sentiment_score = 0.0 if sentiment_score is None else sentiment_score
    sell_through = 0.0 if sell_through is None else sell_through

    if age_ratio < 0.18:
        return "introduction"
    if revenue_change >= 0.12 and sentiment_score >= 0.15:
        return "growth"
    if revenue_change >= -0.18 and sell_through >= 0.42:
        return "maturity"
    return "decline"


def risk_score_from_signals(
    sentiment_delta: float | None,
    revenue_change: float | None,
    return_rate: float | None,
    stockout_ratio: float | None,
) -> float:
    sentiment_delta = 0.0 if sentiment_delta is None else sentiment_delta
    revenue_change = 0.0 if revenue_change is None else revenue_change
    return_rate = 0.0 if return_rate is None else return_rate
    stockout_ratio = 0.0 if stockout_ratio is None else stockout_ratio

    score = 18.0
    score += max(0.0, -sentiment_delta) * 110.0
    score += max(0.0, -revenue_change) * 70.0
    score += return_rate * 95.0
    score += stockout_ratio * 55.0
    score -= max(0.0, revenue_change) * 15.0
    return round(clamp(score, 0.0, 100.0), 2)


def opportunity_score_from_signals(
    sentiment_score: float | None,
    revenue_change: float | None,
    review_count: int | None,
) -> float:
    sentiment_score = 0.0 if sentiment_score is None else sentiment_score
    revenue_change = 0.0 if revenue_change is None else revenue_change
    review_count = 0 if review_count is None else review_count

    score = 22.0
    score += max(0.0, sentiment_score) * 36.0
    score += max(0.0, 0.12 - revenue_change) * 40.0
    score += min(review_count, 400) / 20.0
    return round(clamp(score, 0.0, 100.0), 2)


def risk_bucket_from_score(score: float | None) -> str:
    score = 0.0 if score is None else score
    if score >= 75.0:
        return "critical"
    if score >= 55.0:
        return "watch"
    return "stable"

