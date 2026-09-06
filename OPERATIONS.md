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

`docker-compose.yml` carries two lines that must not be removed:

```yaml
init: true        # tini as pid 1 — reaps orphans. uvicorn cannot.
pids_limit: 1024  # a leak costs THIS CONTAINER, not the machine
```

`pids_limit` is sized for real work, not tightly: **the pids cgroup counts
threads**, and a single headless Chromium is roughly 100 tasks. Two uvicorn
workers each booting a browser sit comfortably under 1024; the 20k runaway
does not.

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

Field 5 sitting near 32768 with a large field 4 is the tell. To attribute
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

Two tables:

| table | holds |
|---|---|
| `domain_quality` | `domain, thin_streak, good_count, last_thin_at` |
| `dead_urls` | `url, reason, expires_at` — permanent 404/410s |

A domain is skipped only when it has **zero** good responses, a `thin_streak`
of 5 or more, and its last thin response was within 24h. One good response
zeroes the streak permanently. That three-part rule is deliberate, and
`seekingalpha.com` is why: measured at `thin_streak` 10 with `good_count` 10, it
is genuinely bimodal, and a plain blocklist would have dropped it.

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
curl -s http://10.0.0.16:8001/health | jq '{build, checks, status}'
```

`build.sha` is **trading-service's** commit, not this repo's — the scraper code
being shipped is trading-service's. The deploy also warns if that tree has
uncommitted scraper changes, which would put code in the image that exists in
no commit.

⚠ `/health` can now return **503**, which it never could before (it returned a
hardcoded literal, so the health gate only ever tested "uvicorn is accepting
sockets"). A 503 means the shared httpx client is gone. A degraded failure cache
is reported in `checks` but deliberately does NOT flip the status — memory-only
costs one wasted fetch per URL, it does not fail a scrape.

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
- [ ] No alert exists on host pid pressure. Both outages were first reported
      by a human noticing a dead website. Concurrent browsers are now capped at
      4 per process (`SCRAPER_MAX_BROWSERS`), which bounds the leak rate but
      does not alert on it.
- [ ] `domain_quality` is per-DOMAIN, but the news collector iterates 27 RSS
      **feeds**. A feed whose articles all live on skipped domains is still
      fetched and parsed every cycle before anything is skipped.
- [ ] There is no "last full-text success" TIMESTAMP. `last_seen` (added with
      the v1 schema migration) records when a domain was last *seen*, not when
      it last gave us a real article, so "when did this domain last work?" is
      still unanswerable from this table.
- [ ] trading-service imports the same `app/scraper` module tree but has no
      `/app/logs`, so its copy degrades to memory-only with one warning. The
      cache is only real inside THIS container.
- [ ] The scraper subtree has no metrics at all — every observable is a log
      line. There is no success rate by engine or domain, no skip counter, and
      no browser/pid gauge, so the questions this document tells you to ask
      during an incident can only be answered by reading logs.

## Schema migrations (2026-09-06)

`failure_cache.db` now carries `PRAGMA user_version` and a migration ladder.
This matters because the database **outlives the deploy** since `3e5651c`: an
old file meets new code every time. Before the ladder, the first added column
would have raised `no such column`, been classified as a permanent fault, and
silently disabled the shared store on every worker behind a single warning.

Adding a column: bump `_SCHEMA_VERSION` in
`trading-service/app/scraper/core/failure_cache.py` and add the `ALTER` to
`_migrate`. A database written by a NEWER build is detected and left alone
rather than downgraded.
