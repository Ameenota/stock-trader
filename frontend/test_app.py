"""Deterministic smoke tests for the Dash frontend (no network required)."""

from datetime import datetime, timezone
import unittest

import pandas as pd

import app
from data import DashboardData


class DashboardSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        now = datetime.now(timezone.utc)
        self.data = DashboardData(
            snapshot={
                "timestamp": now,
                "account_number": "••••48661",
                "total_equity": 105.0,
                "total_cash": 15.0,
                "buying_power": 12.0,
                "unrealized_gain_loss": 5.0,
                "unrealized_gain_loss_percent": 5.0,
                "holdings": [
                    {"symbol": "NVDA", "equity": 50.0},
                    {"symbol": "META", "equity": 40.0},
                ],
                "summary": "Hold both positions while risk controls remain satisfied.",
            },
            recommendations=pd.DataFrame(
                [
                    {
                        "ticker": "NVDA",
                        "raw_score": 0.61,
                        "relative_rank": 1,
                        "signal": "STRONG BUY",
                        "current_price": 175.2,
                        "moving_average_20d": 168.0,
                        "analyst_consensus": "buy",
                        "thesis": "Positive AI demand and improving momentum.",
                        "timestamp": now,
                        "target_weight": 0.3,
                        "rsi": 58.0,
                        "macd": 1.2,
                        "macd_signal": 0.9,
                        "drawdown_pct": -3.0,
                        "sentiment_ewma": 0.5,
                        "sentiment_volatility": 0.1,
                        "forward_pe": 30.0,
                    }
                ]
            ),
            graveyard=pd.DataFrame(
                [
                    {
                        "ticker": "AMD",
                        "current_price": 160.0,
                        "sma_50": 165.0,
                        "momentum": 0.97,
                        "thesis": "Below screening threshold",
                        "timestamp": now,
                    }
                ]
            ),
            trades=pd.DataFrame(
                [
                    {
                        "timestamp": now,
                        "ticker": "NVDA",
                        "action": "STRONG BUY",
                        "amount_usd": 30.0,
                        "reasoning": "Initial allocation",
                        "dry_run": False,
                    },
                    {
                        "timestamp": now,
                        "ticker": "META",
                        "action": "LIQUIDATE",
                        "amount_usd": 20.0,
                        "reasoning": "Risk exit",
                        "dry_run": True,
                    },
                ]
            ),
            headlines=["NVDA announces results"],
        )

    def test_complete_dashboard_renders(self) -> None:
        layout, records = app.dashboard_layout(self.data)
        self.assertEqual(layout.to_plotly_json()["type"], "Main")
        self.assertEqual(len(records), 2)

    def test_trade_filters_exclude_dry_runs_by_default(self) -> None:
        records = app.normalized_trade_records(self.data.trades)
        result = app.trade_table(records, "NVD", "BUY", False)
        self.assertEqual(result.to_plotly_json()["type"], "Div")

    def test_pages_and_health_endpoint(self) -> None:
        self.assertEqual(app.decision_logic.layout().to_plotly_json()["type"], "Main")
        client = app.server.test_client()
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.get("/health").json, {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
