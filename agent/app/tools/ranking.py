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

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Union

class SentimentAnalysis(BaseModel):
    ticker: str = Field(description="The ticker symbol of the asset. Must match the key from the news dictionary.")
    raw_score: float = Field(description="The raw sentiment score from -1.0 to 1.0.")
    thesis: str = Field(description="The thesis/reasoning behind the score based on the news.")

class SentimentAnalysisResponse(BaseModel):
    analyses: List[SentimentAnalysis] = Field(description="List of sentiment analysis results.")

def process_sentiment_rankings(
    analyses: Union[SentimentAnalysisResponse, List[SentimentAnalysis], List[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    """Sorts sentiment analyses by raw_score and assigns relative_rank and signal.
    
    Rules:
    - Sort by raw_score ascending (lowest first, highest last).
    - Assign relative_rank (1 to 10, where 1 is lowest score and 10 is highest score).
    - The bottom 3 ranked assets (ranks 1, 2, 3) get 'LIQUIDATE' signal.
    - The top-ranked assets (ranks 4 to 10) get 'STRONG BUY' only if raw_score > 0.2, otherwise 'HOLD'.
    """
    # Extract list of items
    if isinstance(analyses, SentimentAnalysisResponse):
        items = analyses.analyses
    elif isinstance(analyses, dict) and "analyses" in analyses:
        items = analyses["analyses"]
    else:
        items = analyses

    # Convert items to list of dicts to standardise
    raw_list = []
    for item in items:
        if isinstance(item, BaseModel):
            raw_list.append(item.model_dump())
        elif isinstance(item, dict):
            raw_list.append(item.copy())
        else:
            raw_list.append({
                "ticker": getattr(item, "ticker"),
                "raw_score": getattr(item, "raw_score"),
                "thesis": getattr(item, "thesis")
            })

    # Sort by raw_score ascending
    sorted_list = sorted(raw_list, key=lambda x: x["raw_score"])

    # Assign ranks and signals
    ranked_results = []
    for index, item in enumerate(sorted_list):
        # Rank starts at 1, goes up to len(sorted_list)
        rank = index + 1
        
        if rank <= 3:
            signal = "LIQUIDATE"
        else:
            if item["raw_score"] > 0.2:
                signal = "STRONG BUY"
            else:
                signal = "HOLD"
                
        ranked_results.append({
            "ticker": item["ticker"],
            "raw_score": item["raw_score"],
            "thesis": item["thesis"],
            "relative_rank": rank,
            "signal": signal
        })
        
    return ranked_results
