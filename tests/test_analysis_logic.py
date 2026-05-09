from __future__ import annotations

import unittest

from src.ecom_lifecycle.analysis_logic import (
    classify_lifecycle_stage,
    opportunity_score_from_signals,
    risk_bucket_from_score,
    risk_score_from_signals,
)


class AnalysisLogicTests(unittest.TestCase):
    def test_growth_classification(self) -> None:
        stage = classify_lifecycle_stage(0.25, 0.21, 0.44, 0.78)
        self.assertEqual(stage, "growth")

    def test_decline_classification(self) -> None:
        stage = classify_lifecycle_stage(0.86, -0.34, -0.12, 0.18)
        self.assertEqual(stage, "decline")

    def test_risk_buckets(self) -> None:
        high = risk_score_from_signals(-0.42, -0.28, 0.17, 0.22)
        low = risk_score_from_signals(0.08, 0.11, 0.02, 0.03)
        self.assertEqual(risk_bucket_from_score(high), "critical")
        self.assertEqual(risk_bucket_from_score(low), "stable")

    def test_opportunity_score_is_bounded(self) -> None:
        score = opportunity_score_from_signals(0.91, -0.18, 800)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)


if __name__ == "__main__":
    unittest.main()
