# Post-Deployment TODOs

- [x] Purge Git history of all historical commits containing the raw Robinhood account number. (Completed)
  - Utilized `git filter-branch` to rewrite commits starting from `f68844a` and replaced the raw account number with the placeholder `ROBINHOOD_ACCOUNT_NUMBER`.


- dont log failed orders... we might want to query availaible balance before buying, and just skip the buy if its less

Waiting 1 second for sell orders to settle before buying...

[EXECUTION] Buying 0.044324 shares of AMAT ($28.42). Reason: Increasing weight in AMAT from 0.0% to target 30.0%.
[60058] [Local→Remote] tools/call
[60058] [Remote→Local] 11
   Order result: {'meta': {'rh_error_category': 'invalid_request'}, 'content': [{'type': 'text', 'text': 'API error 400: {"detail":"Not enough buying power."}'}], 'isError': True}
/Users/sagar/Documents/ML/stock-trader/agent/.venv/lib/python3.12/site-packages/google/auth/_default.py:113: UserWarning: Your application has authenticated using end user credentials from Google Cloud SDK without a quota project. You might receive a "quota exceeded" or "API not enabled" error. See the following page for troubleshooting: https://cloud.google.com/docs/authentication/adc-troubleshooting/user-creds.
  warnings.warn(_CLOUD_SDK_CREDENTIALS_WARNING)

- what does cash buying even mean?
[EXECUTION] Buying 0.108333 shares of CASH ($9.47). Reason: Increasing weight in CASH from 0.0% to target 10.0%.
[60058] [Local→Remote] tools/call
[60058] [Remote→Local] 12
   Order result: {'meta': {'rh_error_category': 'invalid_request'}, 'content': [{'type': 'text', 'text': 'API error 400: {"detail":"Not enough buying power."}'}], 'isError': True}
/Users/sagar/Documents/ML/stock-trader/ag




.12/site-packages/google/auth/_default.py:113: UserWarning: Your application has authenticated using end user credentials from Google Cloud SDK without a quota project. You might receive a "quota exceeded" or "API not enabled" error. See the following page for troubleshooting: https://cloud.google.com/docs/authentication/adc-troubleshooting/user-creds.
  warnings.warn(_CLOUD_SDK_CREDENTIALS_WARNING)
HTTP Error 404: {"quoteSummary":{"result":null,"error":{"code":"Not Found","description":"Quote not found for symbol: PSTG"}}}
HTTP Error 404: {"quoteSummary":{"result":null,"error":{"code":"Not Found","description":"Quote not found for symbol: ANSS"}}}
$PSTG: possibly delisted; no price data found  (period=3mo) (Yahoo error = "No data found, symbol may be delisted")
$ANSS: possibly delisted; no price data found  (period=3mo) (Yahoo error = "No data found, symbol may be delisted")
/Users/sagar/Documents/ML/stock-trader/agent/.venv/lib/python3.12/site-packages/google/auth/_default.py:113: UserWarning: Your application has authenticated using end user credentials from Google Cloud SDK without a quota project. You might receive a "quota exceeded" or "API not enabled" error. See the following page for troubleshooting: https://cloud.google.com/docs/authentication/adc-troubleshooting/user-creds.
  warnings.warn(_CLOUD_SDK_CREDENTIALS_WARNING)
   Successfully ingested SPY benchmark price: $733.92
   Daily analysis pipeline finished (metrics gathered).
