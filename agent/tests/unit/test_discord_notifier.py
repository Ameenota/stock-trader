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

import os
import unittest
from unittest.mock import patch, MagicMock
from app.app_utils.discord_notifier import send_discord_webhook

class TestDiscordNotifier(unittest.TestCase):
    
    @patch("urllib.request.urlopen")
    @patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/mock_id/mock_token"})
    def test_send_discord_webhook_success_dict(self, mock_urlopen):
        # Mock successful post response
        mock_response = MagicMock()
        mock_response.status = 204
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        summary = "Recommended to maintain holdings in MU (30.0%) and cash."
        approved_allocations = [{"ticker": "MU", "weight_pct": 0.30}]
        decisions = [{"ticker": "MU", "signal": "STRONG BUY", "thesis": "Solid news sentiment."}]
        
        result = send_discord_webhook(
            summary=summary,
            approved_allocations=approved_allocations,
            decisions=decisions,
            is_dry_run=True
        )
        
        self.assertTrue(result)
        mock_urlopen.assert_called_once()
        
    @patch("urllib.request.urlopen")
    def test_send_discord_webhook_missing_url(self, mock_urlopen):
        # Test that it gracefully returns False if webhook URL is not set
        if "DISCORD_WEBHOOK_URL" in os.environ:
            del os.environ["DISCORD_WEBHOOK_URL"]
            
        result = send_discord_webhook(
            summary="test",
            approved_allocations=[],
            decisions=[],
            is_dry_run=True
        )
        
        self.assertFalse(result)
        mock_urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    @patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/mock_id/mock_token"})
    def test_send_discord_webhook_with_execution_result(self, mock_urlopen):
        # Mock successful post response
        mock_response = MagicMock()
        mock_response.status = 204
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        summary = "Rebalanced portfolio."
        approved_allocations = [{"ticker": "AAPL", "weight_pct": 0.30}]
        decisions = [{"ticker": "AAPL", "signal": "STRONG BUY", "thesis": "Solid news sentiment."}]
        execution_result = {
            "sells": [{"ticker": "MSFT", "shares": 10.0, "amount_usd": 1500.0, "liquidate": True, "reasoning": "Out"}],
            "buys": [{"ticker": "AAPL", "shares": 5.0, "amount_usd": 1000.0, "reasoning": "In"}],
            "buy_power_skip": False
        }
        
        result = send_discord_webhook(
            summary=summary,
            approved_allocations=approved_allocations,
            decisions=decisions,
            is_dry_run=True,
            execution_result=execution_result
        )
        
        self.assertTrue(result)
        mock_urlopen.assert_called_once()

