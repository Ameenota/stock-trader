from pathlib import Path


def test_dashboard_fails_closed_to_one_default_real_account():
    source = (Path(__file__).parents[3] / "frontend" / "app.py").read_text()
    assert "len(rows) != 1" in source
    assert "account_type='REAL'" in source
    assert "is_dashboard_default=TRUE" in source
    assert "refusing a global fallback" in source


def test_account_bearing_dashboard_queries_are_filtered():
    source = (Path(__file__).parents[3] / "frontend" / "app.py").read_text()
    assert source.count("WHERE account_id = @account_id") >= 3
    assert source.count("AND account_id = @account_id") >= 2
    assert source.count('ScalarQueryParameter("account_id"') >= 5
