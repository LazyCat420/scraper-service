# scraper-service — agent notes

## Where the trading-cycle design lives

See `finance/trading/AGENTS.md` -> *Where the trading-cycle design lives*
(tickets in `trading-client/documentation/tickets.jsonl` carry `owner: scraper-service`).

Scraper-relevant sections there: `12-security-and-dependencies.md` covers the
SSRF/redirect guards, credentials and dependency baselines that this service participates in, and
`02-containers-and-data.md` says what this container owns and how the cycle talks to it.

Local operational notes stay here: `OPERATIONS.md` (deploy/run) and `audit/` (audit scripts and
their findings). Those are scraper-specific and are not duplicated in the cycle document.
