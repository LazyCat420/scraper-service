# Operating scraper-service

## ⚠ This container took the whole NAS down, twice (2026-08-20)

**What happened:** every failed scrape orphaned a Chromium, and nothing in
this container ever reaped it. `uvicorn` is pid 1 here, and an app running
as pid 1 is not an init — it never `wait()`s — so each orphan reparented to
it became a **permanent zombie**. They accumulated to **20,179**.

The host's pid space is `kernel.pid_max = 32768`. At 21,024 processes,
**`fork()` began failing system-wide with `EAGAIN`**, which is not survivable
for a machine:

- the Docker daemon died and could not restart
- systemd lost its D-Bus name, so **no unit could start** — DSM's Container
  Manager restart button and `synopkg restart` both did nothing
- sshd could still authenticate but could not spawn a session
  (`exec request failed on channel 0`, which reads like a key problem and
  is not)
- every NAS-hosted site returned 502, while ping, DSM and the databases all
  looked perfectly healthy

Full post-mortem, including the diagnosis path and the recovery that freed
~20k pids without a reboot:
**`trading-service/docs/INCIDENT_2026-08-20_NAS_PID_EXHAUSTION.md`**.

## What now protects the host

### ⚠ `pids_limit` DOES NOT WORK ON THIS BOX, and never has (measured 2026-09-06)

`docker-compose.yml` carries `pids_limit: 1024`, and this document used to
present it as one of "two lines that must not be removed" — the one that makes
"a leak cost THIS CONTAINER, not the machine". **That is false here.** Every
deploy prints, and everyone has been scrolling past:

```
scraper-service Your kernel does not support PIDs limit capabilities
                or the cgroup is not mounted. PIDs limit discarded.
```

Measured on the live NAS after the 2026-09-06 deploy:

```sh
$ sudo docker inspect scraper-service --format '{{.HostConfig.PidsLimit}}'
<nil>                       # not 1024 — no limit is applied at all

$ grep -w pids /proc/cgroups
                            # no output: there is no pids controller

$ uname -r
4.4.302+                    # DSM's kernel; enabled controllers are
                            # cpuset cpu cpuacct blkio memory devices freezer
```

So the containment half of the mitigation is **not in effect**, and was not in
effect during either outage or at any point since. A Chromium leak here can
still reach the host's pid space and take the machine down exactly as it did
twice on 2026-08-20. Leave the line in — it costs nothing and becomes real if
the box ever runs a kernel with the controller — but do not count on it.

### What actually protects the host

| | status | what it does |
|---|---|---|
| `init: true` | **works** (`Init=true`) | tini as pid 1 reaps orphans; uvicorn cannot |
| `memory: 4G` | **works** (`Memory=4294967296`) | bounds RAM, not process count |
| `SCRAPER_MAX_BROWSERS` (default 4) | **works** — in-process | caps concurrent Chromiums per uvicorn worker |
| `pids_limit: 1024` | **DISCARDED** | nothing |

With the cgroup absent, the browser cap added on 2026-09-06
(`app/scraper/engines/playwright_engine.py`) is the only thing bounding how many
Chromiums this service can hold at once. It is a process-wide semaphore, so it
binds per uvicorn worker: 2 workers x 4 browsers x ~100 tasks ≈ 800 tasks worst
case, against a host `pid_max` of 32768. That is the budget now — chosen when
the number it was derived FROM turned out not to be enforced, which is worth
knowing before raising it.

`init: true` is doing the heavy lifting: a reaped orphan never accumulates, and
accumulation is what exhausted the pid space. But tini reaping regardless is
also what can MASK a `close()` that is still leaking, which is why the
close-on-failure behaviour is pinned by a test rather than watched as a number
(`trading-service/tests/unit/test_playwright_engine_closes_browser.py`).

The engine-side leak — `browser.close()` reached only on the happy path —
is fixed in **`trading-service@b75c0e5`**, which owns `app/scraper`.
**This repo's `app/` is a gitignored build artifact**: a clean `git diff`
here proves nothing about what the image contains. Rebuild from
trading-service's source to pick the fix up.

## Checking for the leak on a live box

If services are unreachable and the daemon looks dead, check the pid space
*before* suspecting disk or memory (both were fine here — 10% used, 15 GB
free):

```sh
cat /proc/loadavg      # field 4 = running/TOTAL_THREADS, field 5 = last pid issued
```

Field 5 sitting near 32768 with a large field 4 is the tell. While the
scraper still answers, `curl -s http://10.0.0.16:8001/health/pids` reads the
same two fields and classifies them (see *PID pressure probe* below). To attribute
it, on a box where `ps` and `pgrep` no longer work (they need to fork), use
`/proc` and bash builtins only:

```sh
for p in /proc/[0-9]*; do read -r c < "$p/comm" 2>/dev/null && echo "$c"; done \
  | sort | uniq -c | sort -rn | head
```

A sample process whose `stat` field 3 is `Z` is a zombie — **killing it does
nothing, it is already dead**. Take field 4 (its parent) and read that
parent's `/proc/<pid>/cgroup` to identify the container. Killing the
container's **live** processes reparents the zombies to pid 1, which reaps
them.

⚠ That frees the pids but does **not** finish the recovery: once systemd has
lost its bus name it does not get it back (`kill -USR1 1` and `kill -TERM 1`
were both tried and failed). **A reboot is still required** — clearing the
pids first is what makes it a clean one.

## What the container learns, and where it keeps it (2026-09-03)

`/app/logs/failure_cache.db` is not a log. It is the record of what this
service has **learned about the web**, and the engine reads it before it makes
any network request at all — `auto_engine` calls `failure_cache.check(url)` and
`should_skip_domain(domain)` in phases 0 and 0b, ahead of the fetch.

Two tables (schema v2, `PRAGMA user_version = 2`):

| table | holds |
|---|---|
| `domain_quality` | `domain, thin_streak, good_count, last_thin_at, last_seen, browser_tries, browser_successes, last_browser_at` |
| `dead_urls` | `url, reason, expires_at` — confirmed 404/410s and Playwright-confirmed empty links (7-day TTL, `SCRAPER_FAILURE_TTL_S=604800`) |

A domain is skipped in `should_skip_domain` only when it has **zero** good
responses, a `thin_streak` of 5 or more, and its last thin response was within
24h; `browser_is_hopeless` applies the parallel 5-try / 0-success / 24h rule to
Playwright escalations so sites whose browser path never yields content still get
one daily probe without burning Chromium slots on every article. Known hard-paywall
or bot-walled hosts (`UNSCRAPABLE_DOMAINS`: `seekingalpha.com`, `reuters.com`,
`streetinsider.com`, `chartmill.com`, `thestreet.com`) are skipped before fetch
and again if an HTTP redirect lands on one.

**Until 2026-09-03 this record lived inside the container, on no volume, and
every rebuild erased it.** The service then re-learned each domain one wasted
fetch per URL at a time, silently — nothing logs "I have forgotten everything".

What was in it when it was measured on the live container that day:

| | |
|---|---|
| domains learned | 254 |
| dead URLs | 8 |
| domains earning a skip | 7 |

The seven: `www.investors.com` at a 19-thin streak, then `www.zacks.com`,
`biztoc.com`, `www.youtube.com`, `www.ft.com`, `www.marketwatch.com`, `x.com`.

`docker-compose.yml` now mounts a **named volume** at `/app/logs`. Named rather
than a bind mount because SQLite in WAL mode wants a real filesystem, not a
Synology bind path. The image ships `/app/logs` empty, so the mount hides
nothing, and Docker seeds a new named volume from the image directory — which
is what gives it the right `appusr` (uid 1001) ownership.

**Deploying this change is not enough on its own.** A fresh volume starts empty,
so the 254 rows have to be carried across or the cache silently restarts the
learning — the exact failure the volume exists to prevent. What was done:

```bash
# BEFORE replacing the container: back the live DB up through SQLite, not cp
sudo docker exec scraper-service python -c "
import sqlite3
s=sqlite3.connect('/app/logs/failure_cache.db'); d=sqlite3.connect('/tmp/fc.db')
s.backup(d)"                       # cp of a WAL database can copy a torn file
sudo docker cp scraper-service:/tmp/fc.db /volume1/docker/scraper-service/seed.db
# ...deploy... then, into the new volume:
sudo docker cp /volume1/docker/scraper-service/seed.db scraper-service:/tmp/seed.db
sudo docker exec scraper-service python -c "
import sqlite3
live=sqlite3.connect('/app/logs/failure_cache.db'); seed=sqlite3.connect('/tmp/seed.db')
live.executemany('insert or replace into domain_quality values (?,?,?,?)',
                 seed.execute('select domain,thin_streak,good_count,last_thin_at from domain_quality'))
live.executemany('insert or replace into dead_urls values (?,?,?)',
                 seed.execute('select url,reason,expires_at from dead_urls'))
live.commit()"
```

Verified after the deploy: 254 / 8 restored, all seven skips intact.

To read the current state at any time:

```bash
sudo docker exec scraper-service python -c "
import sqlite3; c=sqlite3.connect('/app/logs/failure_cache.db')
print(c.execute('select count(*) from domain_quality').fetchone())
print(list(c.execute('select domain,thin_streak,good_count from domain_quality'
                     ' where good_count=0 and thin_streak>=5 order by thin_streak desc')))"
```

## Authentication (2026-09-06)

`/scrape`, `/collect` and `/stream` require the `X-Scraper-Key` header. It is
enforced only when `SCRAPER_API_KEY` is set — **an unset key means no auth at
all**, which is how this service ran until 2026-09-06.

That shape is deliberate: it makes the rollout safe in this order, with no
window where a live cycle eats a 401.

```
1. deploy scraper-service   # key unset everywhere -> open, exactly as before
2. set SCRAPER_API_KEY in trading-service's .env, redeploy it
3. set SCRAPER_API_KEY in scraper-service's .env, restart
```

`/health` is never gated — the container healthcheck is a plain `wget` with no
headers, so gating it would restart-loop the container.

Check which mode a running container is in — it says so at boot:

```sh
sudo docker logs scraper-service 2>&1 | grep "API key auth"
```

## Which commit is running? (2026-09-06)

`/health` now answers this. It could not before: `app/` is a gitignored build
artifact, so `git diff` in this repo is trivially clean whatever the image
holds, and the staged copy silently drifted (measured 2026-09-06: `app/scraper`
matched the build byte-for-byte while `text_utils.py` was 66 lines behind).

```sh
curl -s http://10.0.0.16:8001/health | jq '{status, build, checks, admission, rate_limiter, failure_cache}'
```

`build.sha` is **trading-service's** commit, not this repo's — the scraper code
being shipped is trading-service's. The deploy also warns if that tree has
uncommitted scraper changes, which would put code in the image that exists in
no commit.

⚠ `/health` can now return **503**, which it never could before (it returned a
hardcoded literal, so the health gate only ever tested "uvicorn is accepting
sockets"). A 503 means the shared httpx client is gone. A degraded failure cache
is reported in `checks.failure_cache` and top-level `failure_cache` (`entries`,
`max_entries`, `lost_writes`, `store_enabled`) without flipping overall status —
memory-only costs one wasted fetch per URL rather than failing scrapes.

## Search engines: SearXNG sidecar (2026-10-06)

The free search engines bot-block this network's one public IP, and every
scraping attempt deepens a block that every service in the house shares. General
web search for every project goes through `lazy-agent-service`'s
`POST /execute/web_search` (Exa, keyless, one cache and one rate limit), while
`lazy-agent-service` also actively calls `POST /collect` with `source="searxng"`
for SearXNG meta-search.

- **SearXNG sidecar:** `searxng/settings.yml` keeps only `bing` and `wikipedia`,
  the engines `SEARXNG_ENGINES` pins. A request without an `engines` parameter
  can no longer reach Google, Startpage or the other defaults.
  `deploy.sh` now syncs `searxng/settings.yml` to the NAS on every deploy and
  restarts the sidecar when the file changed. SearXNG reads its settings only
  at start. Before 2026-10-06 the file had been copied by hand once, on
  2026-09-21, and repo changes never reached it.

## Dependency pinning and security refresh 2026-10-22

`requirements.txt` had loose specifiers (`lxml>=5.0.0`, `urllib3>=2.0.2`, ...), so
`pip-audit` could not check it and every Docker build resolved "whatever is newest
today". All direct dependencies are now exact `==` pins, resolved and audited on the
full tree (Python 3.12 and the Dockerfile's 3.11, both 137 packages, identical except
numpy/networkx/scipy which are transitive and Python-version dependent).

| Package | From | To | Why |
|---|---|---|---|
| fastapi | 0.115.12 | 0.161.0 | 0.115.x caps starlette below 0.47; needed to reach a fixed starlette |
| starlette (new explicit pin) | 0.46.2 (transitive) | 1.9.0 | 7 advisories, fixed in 0.47.2 / 0.49.1 / 1.0.1 / 1.1.0 / 1.3.0 / 1.3.1 |
| pydantic / pydantic_core | 2.11.3 / 2.33.1 | 2.13.4 / 2.46.4 | required by fastapi 0.161 |
| pydantic-settings | 2.13.1 | 2.14.2 | CVE-2026-58203 |
| yt-dlp | 2026.8.19 | 2026.10.21 | extractors break constantly; newest |
| urllib3 | `>=2.0.2` | 2.8.0 | pinned to the audited release |
| requests | `>=2.32.0` | 2.34.2 | pinned |
| lxml | `>=5.0.0` | 6.1.3 | pinned to today's resolution |
| fake-useragent | `>=2.0.3` | 2.2.0 | pinned to today's resolution |
| tenacity | `>=8.5.0` | 9.2.1 | pinned to today's resolution |
| structlog | `>=24.4.0` | 26.1.0 | pinned to today's resolution |

pip-audit on the resolved set: before, 15 findings in 2 packages (starlette 0.46.2,
pydantic-settings 2.13.1); after, none (3.12 and 3.11). Tests: `tests/` 16 passed on
the old and the new manifest; `scraper_main` imports and `GET /health` returns 200
under the new set. `app/` and `lazycat/` are build copies from trading-service, so
fastapi/starlette/pydantic here track trading-service's lock. Redeploy needed (not
done here); re-probe `/health` and `/stream` after deploying.

## Open items

- [x] ~~Not yet deployed as of 2026-08-20 — the running image still leaks.~~
      Shipped; the 2026-09-03 rebuild carries `b75c0e50`.
- [x] ~~The `finally` fix is pinned by no test.~~ Now pinned in
      `trading-service/tests/unit/test_playwright_engine_closes_browser.py`,
      parametrised over goto / new_context / new_page / evaluate / screenshot
      failures plus cancellation. The previous test lived in this repo's
      `tests/`, which has no pytest config and is outside trading-service's
      `testpaths` — so nothing ran it.
- [x] ~~Nothing prunes the volume.~~ `prune()` now ages out `domain_quality`
      (`SCRAPER_DOMAIN_MAX_AGE_S`, default 90d) as well as `dead_urls`, and is
      reachable from the read path — it previously ran only from `record()`,
      which fires on a 404/410, measured at 8 rows in 14 days.
- [x] ~~No alert exists on host pid pressure.~~ Resolved 2026-11-07:
      `GET /health/pids` (unauthenticated, in `scraper_main.py`) reads
      `/proc/loadavg` and `/proc/sys/kernel/pid_max` and answers `ok` / `warn` /
      `critical` — see *PID pressure probe* below. Every non-`ok` read is logged
      as a warning, so a poller (or `docker logs`) sees the leak before a human
      notices a dead website. Pinned by
      `tests/test_health_probe_and_feeds.py::test_pid_pressure_*`.
- [x] ~~`domain_quality` is per-DOMAIN, but the news collector iterates RSS
      **feeds**.~~ Closed 2026-11-07 as documented behaviour (26 active feeds in
      `RSS_FEEDS` after removing the dead Yahoo Finance RSS endpoint in `S-18`,
      `trading-service@f4e85233`): per-feed state exists since 2026-09-21
      (`feed_status` table, `GET /health/feeds`), so a feed that keeps failing is
      visible by URL. Skipping stays per-domain on purpose — see *Domain and feed
      quality* below.
- [x] ~~There is no "last full-text success" TIMESTAMP.~~ Closed 2026-11-07:
      "when did this source last work?" is answered per feed by
      `feed_status.last_success_at` (exposed as ISO-8601 on `/health/feeds`).
      Per domain, `good_count` and `thin_streak` remain the signal; the skip
      rule needs only those (see below).
- [x] ~~trading-service imports the same `app/scraper` module tree but has no
      `/app/logs`.~~ Closed 2026-11-07 as accepted design: the learned cache
      lives in THIS container's named volume. trading-service's in-process copy
      degrades to memory-only with one warning, which costs one wasted fetch per
      URL and never fails a scrape (`/health` reports a degraded cache in
      `checks` without flipping status).
- [x] ~~The scraper subtree has no metrics at all — every observable is a log
      line.~~ Resolved 2026-10-18 (`trading-service@5a88f552`): `/health` now
      exposes per-engine `engine_counters` (`http`, `playwright`,
      `auto` with `success`, `failure`, `fallback`, `skipped`) and live
      `browser_slots` (`active`, `max`, `available`) from the Playwright
      process semaphore.

## PID pressure probe — `GET /health/pids` (2026-11-07)

The 2026-08-20 outage is a pid-space problem, and `pids_limit` is discarded on
this kernel, so the scraper now reports the host's task count itself:

```sh
curl -s http://10.0.0.16:8001/health/pids | jq
# {"status":"ok","running":3,"total_tasks":812,"last_pid":41234,
#  "pid_max":32768,"task_ratio":0.0248,"warn_at":13107,"critical_at":19660}
```

- **Source:** `/proc/loadavg` field 4 (`running/TOTAL` tasks — not
  pid-namespaced, so inside the container it still counts every task on the
  NAS) and field 5 (last pid issued), against `/proc/sys/kernel/pid_max`.
- **Thresholds:** `warn` at `SCRAPER_PID_WARN_RATIO` (default `0.4`) and
  `critical` at `SCRAPER_PID_CRIT_RATIO` (default `0.6`) of `pid_max`. The
  outage began failing `fork()` at 21,024 of 32,768 (64%).
- **Always HTTP 200.** The verdict is the `status` field. Host-wide pressure
  may come from another container; failing this route frees no pid. The
  Docker healthcheck stays on `/health`.
- **Unreadable `/proc`** answers `status: "unknown"` with an `error` string,
  never a 500.
- **Helper:** `read_pid_pressure()` in `scraper_main.py`; tests in
  `tests/test_health_probe_and_feeds.py`.

## Domain and feed quality (2026-11-07, updated 2026-11-13)

Two different units, on purpose:

| unit | table | written by | read by | effect |
|---|---|---|---|---|
| domain | `domain_quality` (`thin_streak`, `good_count`, `last_thin_at`, `last_seen`, `browser_tries`, `browser_successes`, `last_browser_at`) | every `auto` scrape result + Playwright escalation | `auto_engine` `should_skip_domain` & `browser_is_hopeless` | skip domain for 24h when `good_count == 0` and `thin_streak >= 5`; skip Playwright escalation for 24h when `browser_successes == 0` and `browser_tries >= 5` |
| feed | `feed_status` (`last_success_at`, `last_failure_at`, `consecutive_failures`, `last_error`) | `news_collector` per RSS fetch (`HTTP <code>`, `0 entries`, exceptions) | `GET /health/feeds` (sorted `consecutive_failures DESC, last_failure_at DESC`) | visibility only across the 26 active `RSS_FEEDS` (dead Yahoo Finance RSS removed in `S-18`, `f4e85233`): a feed is never auto-skipped |

A feed is still fetched every cycle even when all its articles land on skipped
domains: the RSS fetch is one cheap request, and the article fetches behind it
are what the domain rule already skips. One good response zeroes a domain's
streak permanently. `prune()` ages out `domain_quality` rows older than
`SCRAPER_DOMAIN_MAX_AGE_S` (default 90 days) and expired `dead_urls` rows older
than `SCRAPER_FAILURE_TTL_S` (default 7 days).

## Schema migrations (2026-09-06, v2 2026-11-13)

`failure_cache.db` carries `PRAGMA user_version` (`_SCHEMA_VERSION = 2`: v1
added `last_seen`; v2 added `browser_tries`, `browser_successes`, and
`last_browser_at` to `domain_quality`) and a migration ladder.
This matters because the database **outlives the deploy** since `3e5651c`: an
old file meets new code every time. Before the ladder, the first added column
would have raised `no such column`, been classified as a permanent fault, and
silently disabled the shared store on every worker behind a single warning.

Adding a column: bump `_SCHEMA_VERSION` in
`trading-service/app/scraper/core/failure_cache.py` and add the `ALTER` to
`_migrate`. A database written by a NEWER build is detected and left alone
rather than downgraded.

## Prism exit — lazy-agent-service (2026-10-16)

prism-service (:7777) is retired for this app. The LLM/agent gateway is
lazy-agent-service at `http://10.0.0.16:5591` (native `/agent`, `/chat`,
`/config`). Set `LAZY_AGENT_URL=http://10.0.0.16:5591` in the NAS `.env` (the
SDK default already matches, so unset also works). Outbound calls send
`x-project: scraper-service` and `x-username: scraper-service`. The scraper
subtree source of truth is `finance/trading/trading-service/app/scraper`
(staged by deploy.sh PRE_BUILD); `app/` and `lazycat/` here are build-time
copies, so the rename lives there and in `platform/lazycat-sdk`.

## E2, E3 & `/health` engine counters (2026-10-18)

Shipped from `trading-service` (`5a88f552` + SearXNG snippet date parser):

1. **Engine chain (`http` → `playwright`):** crawl4ai engine removed 2026-11-04 (0 recoveries in 20 hard URLs; 9–100 s latency). `AutoEngine` falls through from `http` → `playwright` when http fails or returns thin (`< 900` chars) content, unless gated by `browser_is_hopeless` or `UNSCRAPABLE_DOMAINS`.
2. **`E3` (structured `published_at` / `publishedDate` on `/scrape` and SearXNG `/collect`):**
   - `POST /scrape` extracts publication timestamps from metadata dicts, HTML `<meta>` tags (`article:published_time`, `og:published_time`, `datePublished`, `pubdate`, `publishdate`, `dc.date`, `sailthru.date`, `date`), `<time datetime="...">`, and `<script type="application/ld+json">` (`datePublished`, `dateCreated`, `uploadDate`), exposing both `published_at` and `publishedDate` at the top level of `ScrapeResponse` as well as in `data` and `metadata`.
   - `SearxngCollector` (`POST /collect` with `source="searxng"`) populates `published_at` and `publishedDate` from top-level `publishedDate` / `pubdate` fields, and when `SEARXNG_ENGINES=bing` omits top-level dates, parses leading snippet timestamps before `" · "` / `" - "` (both relative expressions like `"1 day ago · ..."` / `"9 hours ago · ..."` and explicit dates like `"Oct 15, 2026 · ..."` / `"2026-10-15 - ..."` / `"15 Oct 2026 · ..."`) into ISO-8601 UTC strings.
3. **`GET /health` operational telemetry:**
   - Exposes `engine_counters` (`http`, `playwright`, `auto` with `success`, `failure`, `fallback`, `skipped`, plus `skip_reasons`) and `browser_slots` (`active`, `max`, `available` from `SCRAPER_MAX_BROWSERS`).

## Cross-worker SQLite state, admission control & skip parity (2026-11-13)

Staged from `trading-service/app/scraper/` (`f76e774d` + `f4e85233`; `C1–C4`, `C1b`, `W0.1`, `W0.3`, `W2.3`, `S-18`) across `uvicorn --workers 2`:

1. **Persistent `failure_cache.db` (`C1`, `C1b`, `W0.1` — `core/failure_cache.py`):**
   - **Schema v2 & 7-day dead-link TTL:** `_SCHEMA_VERSION = 2`, `DEFAULT_TTL_S = 7 * 24 * 3600` (`SCRAPER_FAILURE_TTL_S`), `DEFAULT_MAX_ENTRIES = 4096`. Real HTTP `404`/`410` responses without block-page markers record `dead_link`; UA-sniffed `404` block pages escalate to Playwright first instead of poisoning `dead_urls` (`7ad08fc8`), and `< 120`-char `2xx` shells record `empty_link` only after Playwright also fails.
   - **Domain browser-hopeless skip (`C1b`):** `browser_is_hopeless(domain)` and `record_browser_result()` skip Playwright escalation for 24 h (`SKIP_TTL_S = 86400`) once `browser_successes == 0` and `browser_tries >= 5` (`SKIP_AFTER_THIN = 5`), allowing one probe per day while static `UNSCRAPABLE_DOMAINS` (`seekingalpha.com`, `reuters.com`, `streetinsider.com`, `chartmill.com`, `thestreet.com`) short-circuit both pre-fetch and post-HTTP-redirect.
   - **Lock discipline & write-loss accounting (`W0.1`):** `FailureCache` protects `_entries`, `_last_prune`, and `_lost_writes` under `threading.Lock()` across all cache reads and mutations (`check`, `record`, `clear`, `size`, `stats`, `_prune_locked`) **without holding the lock across SQLite I/O**. When `check()` misses memory and queries `SqliteFailureStore.check()`, it re-acquires `self._lock` and writes `_entries[url]` only if no fresher in-memory entry arrived concurrently. `SqliteFailureStore.record(url, reason, expires_at) -> bool` returns `False` on SQLite write errors; `FailureCache.record()` increments `_lost_writes` (warning on the first lost write, debug thereafter) and surfaces `{"entries", "max_entries", "lost_writes", "store_enabled"}` under `failure_cache` on `GET /health`.
2. **Shared cross-worker `rate_limiter.db` & RFC-9110 `Retry-After` (`C4`, `W0.3` — `core/shared_limiter.py`, `core/rate_limiter.py`, `engines/http_engine.py`):**
   - `SharedRateLimiter` persists per-domain pacing in SQLite WAL `/app/logs/rate_limiter.db` (`SCRAPER_RATE_LIMITER_DB`, `BEGIN IMMEDIATE` atomic slot reservation in `domain_next(key, next_at)`) so configured per-domain rates apply container-wide across both `uvicorn` workers rather than 2×.
   - Wait ceiling `MAX_WAIT_S = 30.0` (`SCRAPER_RATE_LIMITER_MAX_WAIT_S`) raises `RateLimitWaitTooLong` without advancing the slot when a domain is backed up past 30 s, while `HARD_CAP_S = 3600.0` (`SCRAPER_RATE_LIMITER_HARD_CAP_S`) bounds `push_out`. After `MAX_CONSECUTIVE_STORE_ERRORS = 3` SQLite errors, the limiter falls back to in-process memory and reports `db_ok`, `waits`, `wait_ms_total`, `store_errors`, `consecutive_store_errors`, `refused_too_long`, and `pushed_out` under `rate_limiter` on `GET /health`.
   - On HTTP `429` or `503` (`ASKED_TO_WAIT_STATUSES`), `http_engine._parse_retry_after()` parses both RFC-9110 integer/finite-float delay-seconds and HTTP-date headers (`email.utils.parsedate_to_datetime`, clamped `>= 0.0`), pushes out the shared domain slot via `rate_limiter.push_out(domain, asked)`, and returns `engine_used="http (waiting)"`; `AutoEngine` returns `engine_used="auto (waiting)"` without escalating to Playwright or caching the URL as dead.
3. **Shared SQLite WAL operational metrics & `AutoEngine` `skip_reasons` parity (`W2.3` — `core/metrics.py`, `engines/auto_engine.py`):**
   - `MetricsStore` persists engine and skip counters in SQLite WAL `/app/logs/scraper_metrics.db` (`SCRAPER_METRICS_DB_PATH`, table `scraper_counters(bucket, metric, total)`, with temp/in-memory fallback if `/app/logs` is read-only), aggregating operational counts across all `uvicorn` workers on `GET /health`.
   - `AutoEngine._record_auto_skip(skip_reason)` maintains the strict invariant `auto.skipped == sum(skip_reasons.values())` across `skip_reasons` (`dead_link`, `empty_link`, `unscrapable_domain`, `domain_thin`, `browser_hopeless`). A first-time live HTTP `404`/`410` over the network is recorded via `_failed_permanent()` as `engine_used="auto (failed)"` (`auto.failure += 1`, never `skipped`); subsequent hits served from `failure_cache` skip network I/O, return `engine_used="auto (skipped)"`, and increment both `auto.skipped` and `skip_reasons["dead_link" | "empty_link"]`.
4. **Admission gate & health probes (`C3`, `S-18` — `api/admission.py`, `scraper_main.py`, `collectors/feed_registry.py`):**
   - `AdmissionGate` (`admission_slot` FastAPI dependency on `/scrape`, `/scrape/batch`, and `/collect`, paired with a 120 s route deadline on `/scrape` & `/scrape/batch` and off-loop `asyncio.to_thread` HTML/JSON/RSS decoding) bounds each worker to `SCRAPER_ADMISSION_INFLIGHT=8` active requests and `SCRAPER_ADMISSION_WAITING=16` queued callers; excess arrivals fail fast with HTTP `429` + `Retry-After: 5` (`SCRAPER_ADMISSION_RETRY_AFTER_S`) and report live `inflight`, `waiting`, `admitted`, and `rejected` under `admission` on `GET /health`.
   - `GET /health/pids` monitors host PID exhaustion (`/proc/loadavg` vs `pid_max`, warn `0.4` / critical `0.6`, always HTTP 200), and `GET /health/feeds` surfaces per-feed RSS health worst-first (`consecutive_failures DESC, last_failure_at DESC`) with the dead Yahoo Finance RSS endpoint removed from `RSS_FEEDS` (`S-18`, `f4e85233`).


