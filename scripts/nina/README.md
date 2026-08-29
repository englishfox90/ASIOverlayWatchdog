# Driving PFR Sentinel from NINA

These scripts let a NINA **Advanced Sequencer** start and stop Sentinel capture,
with no plugin and no C#. They are Stage 0e of
[`docs/NINA_INTEGRATION_PLAN.md`](../../docs/NINA_INTEGRATION_PLAN.md) — the gate
that decides whether the native plugin (Stages 1–3) is worth building.

| File | Purpose |
|---|---|
| `Invoke-SentinelCapture.ps1` | Does the work. Reads Sentinel's config, calls the control API, waits for the state, exits non-zero on failure. |
| `sentinel-capture-start.bat` | NINA-friendly wrapper — point an External Script instruction here. |
| `sentinel-capture-stop.bat` | Same, for stop. |

## One-time setup

1. In Sentinel, open the **Output** tab and enable the web server.
2. Enable the **Capture Control API**. Sentinel mints a token on first enable.

That is the whole setup. The scripts read the host, port and token straight out
of Sentinel's `config.json`, so there is nothing to type into NINA and no
credential to copy around. The token is never printed or logged.

## Adding it to a sequence

In NINA's Advanced Sequencer, add an **External Script** instruction and set the
script path to the `.bat` file:

```
D:\...\PFRSentinel\scripts\nina\sentinel-capture-start.bat
```

A typical night:

| Where in the sequence | Instruction |
|---|---|
| After the roof opens / before the first target | External Script → `sentinel-capture-start.bat` |
| In the end-of-night set, before parking | External Script → `sentinel-capture-stop.bat` |

## Why the calls block

Both commands wait until capture has genuinely reached the requested state
before returning (up to 30s by default). The sequence therefore does not advance
while capture is still spinning up, which is what makes the step deterministic
rather than a fire-and-forget hope.

Both are **idempotent**. Re-running Start on an already-running capture succeeds
as a no-op, and an aborting sequence that fires Stop twice will not fail. This is
deliberate — a sequence step that errors on a harmless repeat is worse than
useless.

## When a step fails

The script writes a plain-English reason to stdout (visible in NINA's log) and
exits non-zero so NINA marks the step as failed rather than silently continuing.

| Exit | Meaning | Fix |
|---|---|---|
| 2 | Sentinel's `config.json` not found | Sentinel not installed on this machine — pass `-BaseUrl` / `-Token` explicitly |
| 3 | Control API off, or no token | Enable the Capture Control API on Sentinel's Output tab |
| 4 | Sentinel not reachable | Is Sentinel running with the web server enabled? |
| 5 | Auth rejected | Regenerate the token on the Output tab |
| 6 | Timed out reaching the state | Camera slow to start; raise `-TimeoutSeconds` |
| 7 | Capture reported a failure | Check Sentinel's log — usually a camera fault |

## Running it by hand

Worth doing once before you trust it to a night:

```powershell
.\Invoke-SentinelCapture.ps1 -Command start
.\Invoke-SentinelCapture.ps1 -Command stop -TimeoutSeconds 60
```

## Sentinel on a different machine

The control API binds loopback and enforces a `Host` allow-list, so by default it
only accepts calls from the machine Sentinel runs on. If you later split NINA and
Sentinel across two PCs, that is a deliberate decision to revisit (D1 in the
plan) — it needs a LAN bind and a hardened security review, not just a
`-BaseUrl` override.
