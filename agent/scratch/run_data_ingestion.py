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

import json
import sys
import os

# Add the agent directory to python path to allow importing app module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tools.data_ingestion import ingest_market_news


def main():
    print("Fetching and filtering latest 24h news from yfinance for target assets...")
    news = ingest_market_news()
    print("\nResults:")
    print(json.dumps(news, indent=2))


if __name__ == "__main__":
    main()
