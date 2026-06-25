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

from typing import List

# Centralized universe of 40 AI sector and grid infrastructure stocks
TICKER_UNIVERSE = [
    # 1. Original 10 Core Assets (AI core/infrastructure + hedge ETF fallback)
    "NVDA", "AMD", "TSM", "MU", "SMCI", "DELL", "VRT", "ETN", "CEG", "TLT",
    # 2. Big Tech Cloud & LLM Providers
    "MSFT", "GOOGL", "AMZN", "META", "ORCL",
    # 3. Custom ASICs, Networking & Design Tools
    "AVGO", "ANET", "ARM", "SNPS", "CDNS",
    # 4. Semiconductor Manufacturing Equipment
    "ASML", "AMAT", "LRCX", "KLAC", "INTC",
    # 5. Datacenter Utilities & Infrastructure
    "VST", "GE", "PSTG", "HPE",
    # 6. AI Software & Integration Services
    "PLTR", "IBM", "NOW", "ADBE", "SAP",
    # 7. Edge Inference & Monitoring
    "NET", "DDOG", "ANSS",
    # 8. AI-driven Security & Edge Devices
    "CRWD", "PANW", "QCOM"
]

# Currently active subset for daily ingestion and sentiment analysis to optimize token usage
ACTIVE_TICKERS = [
    "NVDA", "AMD", "TSM", "MU", "SMCI", "DELL", "VRT", "ETN", "CEG", "TLT"
]

def get_allowed_tickers() -> List[str]:
    """Returns the centralized list of 40 allowed ticker symbols for trading security guardrails."""
    return TICKER_UNIVERSE

def get_active_tickers() -> List[str]:
    """Returns the subset of 10 ticker symbols currently active in the daily analysis pipeline."""
    return ACTIVE_TICKERS
