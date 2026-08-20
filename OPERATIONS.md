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

## Open items

- [ ] Not yet deployed as of 2026-08-20 — the running image still leaks.
- [ ] The `finally` fix is pinned by no test. After deploy, tini will reap
      regardless, which can mask a `close()` that is still leaking; watch
      the zombie count rather than assuming.
- [ ] No alert exists on host pid pressure. Both outages were first reported
      by a human noticing a dead website.
