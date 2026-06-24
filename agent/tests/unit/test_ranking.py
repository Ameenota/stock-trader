# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pytest
from app.tools.ranking import (
    SentimentAnalysis,
    SentimentAnalysisResponse,
    process_sentiment_rankings,
)

def test_process_sentiment_rankings_logic():
    """Mathematically proves the sorting, relative ranking, and signal logic:
    - Bottom 3 ranked assets get a 'LIQUIDATE' signal.
    - Top-ranked assets (ranks 4 to 10) get a 'STRONG BUY' only if score > 0.2.
    - Otherwise they get 'HOLD'.
    """
    # 10 mock assets with raw scores covering all boundaries:
    # Under 0.2, exactly 0.2, over 0.2, highly negative, neutral, highly positive
    mock_raw_data = [
        {"ticker": "NVDA", "raw_score": 0.8, "thesis": "Extremely positive"},
        {"ticker": "AMD", "raw_score": 0.1, "thesis": "Slightly positive but <= 0.2"},
        {"ticker": "TSM", "raw_score": 0.2, "thesis": "Exactly 0.2 (boundary)"},
        {"ticker": "MU", "raw_score": 0.3, "thesis": "Slightly above 0.2"},
        {"ticker": "SMCI", "raw_score": -0.9, "thesis": "Extremely negative"},
        {"ticker": "DELL", "raw_score": -0.1, "thesis": "Slightly negative"},
        {"ticker": "VRT", "raw_score": 0.0, "thesis": "Neutral"},
        {"ticker": "ETN", "raw_score": 0.5, "thesis": "Positive"},
        {"ticker": "CEG", "raw_score": -0.5, "thesis": "Negative"},
        {"ticker": "TLT", "raw_score": 0.15, "thesis": "Slightly positive"},
    ]

    # Convert to Pydantic objects to simulate Part 1 Agent output
    analyses_list = [SentimentAnalysis(**item) for item in mock_raw_data]
    response = SentimentAnalysisResponse(analyses=analyses_list)

    # Process rankings
    results = process_sentiment_rankings(response)

    # Verify length is exactly 10
    assert len(results) == 10

    # Verify sorting by raw_score ascending
    raw_scores = [r["raw_score"] for r in results]
    assert raw_scores == sorted(raw_scores)

    # Verify ranks are 1 to 10
    ranks = [r["relative_rank"] for r in results]
    assert ranks == list(range(1, 11))

    # Verify bottom 3 assets (ranks 1, 2, 3) get LIQUIDATE
    for result in results[:3]:
        assert result["relative_rank"] in [1, 2, 3]
        assert result["signal"] == "LIQUIDATE"

    # Verify the remaining 7 assets get STRONG BUY if score > 0.2 else HOLD
    for result in results[3:]:
        assert result["relative_rank"] > 3
        score = result["raw_score"]
        if score > 0.2:
            assert result["signal"] == "STRONG BUY"
        else:
            assert result["signal"] == "HOLD"

    # Specific assertions:
    # 1. SMCI should be rank 1 (score -0.9) -> LIQUIDATE
    assert results[0]["ticker"] == "SMCI"
    assert results[0]["signal"] == "LIQUIDATE"

    # 2. NVDA should be rank 10 (score 0.8) -> STRONG BUY (0.8 > 0.2)
    assert results[9]["ticker"] == "NVDA"
    assert results[9]["signal"] == "STRONG BUY"

    # 3. TSM has score 0.2. Since rank > 3, check signal.
    # Score 0.2 is NOT > 0.2 (must be strictly greater), so it should be HOLD.
    tsm_result = next(r for r in results if r["ticker"] == "TSM")
    assert tsm_result["relative_rank"] > 3
    assert tsm_result["signal"] == "HOLD"

    # 4. MU has score 0.3. Since rank > 3 and 0.3 > 0.2, it should be STRONG BUY.
    mu_result = next(r for r in results if r["ticker"] == "MU")
    assert mu_result["relative_rank"] > 3
    assert mu_result["signal"] == "STRONG BUY"


def test_process_sentiment_rankings_different_formats():
    """Verify the utility processes list of dicts, list of Pydantic models, and raw response."""
    raw_list = [
        {"ticker": "NVDA", "raw_score": 0.5, "thesis": "Bullish"},
        {"ticker": "AMD", "raw_score": -0.2, "thesis": "Bearish"},
        {"ticker": "TSM", "raw_score": 0.0, "thesis": "Neutral"},
        {"ticker": "MU", "raw_score": 0.8, "thesis": "Very bullish"},
    ]

    # Test raw list of dictionaries
    results_dicts = process_sentiment_rankings(raw_list)
    assert len(results_dicts) == 4
    assert results_dicts[0]["ticker"] == "AMD"  # lowest score

    # Test list of SentimentAnalysis objects
    obj_list = [SentimentAnalysis(**x) for x in raw_list]
    results_objs = process_sentiment_rankings(obj_list)
    assert len(results_objs) == 4
    assert results_objs[0]["ticker"] == "AMD"
