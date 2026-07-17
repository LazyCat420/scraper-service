# DEPRECATED — merged into the lazy-tool-service bundle (runs in trading-service)

This standalone scraping microservice has been folded **in-process** into the
shared Python app that ships inside **lazy-tool-service** (NAS port 5591). The
code physically lives in **`trading-service/app/scraper/`** (which `lazy-tool-service`
bundles at deploy time) and executes inside the trading-service process — there is
no more separate `scraper-service:8001` container.

## Where everything went (as of 2026-07-17)

- **Engines** (`app/engines/` → `trading-service/app/scraper/engines/`): http,
  playwright, crawl4ai, vision, auto — unchanged, imports rerooted to
  `app.scraper.*`. Chromium is installed in the trading-service Dockerfile
  (`playwright install`).
- **Collectors** (`app/collectors/` → `trading-service/app/scraper/collectors/`):
  reddit, reddit-purge, youtube, news, finnews, discourse, xenforo, kannapedia,
  leafly, duckduckgo, twitter, stocktwits — all 12 moved.
- **Core** (`app/core/` → `trading-service/app/scraper/core/`): `session_manager`
  (now started/stopped by `BootService`, with a lazy fallback), `rate_limiter`,
  `base_engine`, `base_result`.
- **HTTP routes** (`app/api/routes/` → `trading-service/app/scraper/api/routes/`):
  `POST /scrape`, `POST /scrape/batch`, `POST /collect`, `GET /stream/{video_id}`.
  These are wired into trading-service's FastAPI health app (`cycle_main.py`) and
  are now served at **`http://<host>:3031`** (external NAS port; internal 8080).
  The scraper's own `/health` router was intentionally dropped (trading-service
  already serves `/health`).
- **In-process seam**: `trading-service/app/scraper/service.py` +
  `trading-service/app/services/scraper_client.py`. The historical
  `scraper_client.scrape()/.collect()` contract is preserved, but the body now
  calls the folded-in engines/collectors directly instead of POSTing to `:8001`.
- **Agent tools**: the `scrape_url` / `lazy_web_search` MCP tools are unchanged
  and still reach this code through the lazy-tool gateway.

## Callers repointed off `scraper-service:8001` → trading-service `:3031`

trading-service (now in-process), HTML-Notes (`app/config.py`), music-player
(`apps/api/app/services/youtube.py`), treesearch-service
(`docker-compose.yml` / `.env.example` / `src/scraper_client.py`), and
youtube-wallgarden (`nginx.conf` proxy target).

## What was NOT ported / retained

- The standalone FastAPI entrypoint (`app/main.py`), this repo's `Dockerfile`,
  and `docker-compose.yml` are obsolete and no longer deployed.
- This directory (and its `.venv`) is **retained, not deleted**, because the
  Playwright bench/smoke tooling in `youtube-wallgarden` (`package.json`) and
  `HTML-Notes/bench/` still reference `../scraper-service/.venv` as an
  interpreter path. Do not delete the directory until those paths are moved.

## Retirement

- Removed from `vault-service/projects.json`, so `deploy-kit/deploy-all.sh` no
  longer builds or deploys it.
- The NAS container (port **8001**) can be stopped; nothing in the ecosystem
  references it at runtime anymore.
