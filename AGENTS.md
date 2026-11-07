# scraper-service — agent notes

## Where the trading-cycle design lives (2026-11-06)

This service is part of the trading cycle, but the cycle's technical design document lives in
`finance/trading/trading-client/documentation/`: section `12-security-and-dependencies.md` covers the
SSRF/redirect guards, credentials and dependency baselines that this service participates in, and
`02-containers-and-data.md` says what this container owns and how the cycle talks to it.

Open problems are tickets in `trading-client/documentation/tickets.jsonl`; look for
`owner: scraper-service`. Do not start a dated chapter here — open a ticket, or update the matching
section in trading-client.

Local operational notes stay here: `OPERATIONS.md` (deploy/run) and `audit/` (audit scripts and
their findings). Those are scraper-specific and are not duplicated in the cycle document.
