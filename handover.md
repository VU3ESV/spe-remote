# spe-remote — Handover

**Repo:** `~/projects/spe-remote` (canonical; the copy under `~/Documents/Claude/code/spe-remote` is stale, do not touch)
**Branch:** `main`, clean, in sync with `origin/main`
**Last commit:** `aca6c8c` — heartbeat: count RCU frames toward amp liveness, not just CSV
**Date:** 2026-05-14

## What this project is

Python 3 remote-control server for **SPE Expert** HF amplifiers (1.3K-FA, 1.5K-FA, 2K-FA). Runs on a Raspberry Pi, opens the USB-serial port to the amp, and serves a single WebSocket on `:8888` that fans out to:

- the bundled browser dashboard at `http://pi:8888`
- Node-RED on the Pi
- the MacExpert companion app

The Python server is the **only** process that ever opens `/dev/ttyUSB0`. Every other client speaks WebSocket. This is the whole reason the project exists — Node-RED used to hold the serial port directly and locked everyone else out.

## Layout

```
server.py              main async server (serial reader thread + ws broadcast)
power_spe_on.py        DTR-line power-on helper
config.yaml            serial port, baud, poll intervals, temp unit, log level
spe/                   protocol module (parser, command builder, RCU framing)
web/                   browser dashboard (static HTML/JS/CSS, canvas gauges)
systemd/               unit file for spe-remote.service
install-service.sh     installs + enables the systemd unit
uninstall-service.sh   reverse of above
run.sh                 dev launcher
setup.sh               first-time venv + deps install
docs/                  protocol notes, Node-RED sample flow
```

## Recent work (newest first)

1. **`power_on` clients consolidated on the WebSocket path (2026-05-15)** — the Node-RED `vu2cpl-shack` flow used to run a separate Pi-side `exec` node that spawned `python3 /home/vu2cpl/power_spe_on.py` for its `ON_SPE` button, on the (incorrect) theory that the WS server couldn't wake a powered-off amp because the serial *data* link was dead. In fact `spe/power_control.py` `_power_on_sync()` does the same DTR/RTS sequence on the already-open serial handle — and the FTDI hardware lines are controllable via ioctl regardless of whether the amp's CPU is alive. **Correct client-side behaviour:** send the string `power_on` over WebSocket → the server toggles DTR (`DTR=1 → DTR=0 → RTS=1 → wait 1 s → DTR=1 → RTS=0`) → amp starts in 3–4.5 s → the server replies with a `power_result` JSON ack on the same socket. **Do not have other clients spawn `power_spe_on.py` while this service is running** — both would try to manipulate `/dev/ttyUSB0`, you'd hit the same FTDI-handle contention that the Serial-stack fixes (item 8 below) cleaned up. Standalone `power_spe_on.py` in this repo stays as a fallback tool only for the case where `spe-remote.service` itself is down. Documented in `vu2cpl-shack` CLAUDE.md + SHACK_CHANGELOG (commit `fa0a18d`).
2. **RCU counts toward heartbeat liveness** — `serial_handler` now stamps `_last_rcu_at` on every emitted RCU frame and exposes `last_rcu_age`. `presence_heartbeat_loop` reports `serial:"up"` if EITHER CSV or RCU is fresher than `amp_alive_threshold`. Fixes the "POWERED OFF banner appears in STANDBY" bug: the amp slows CSV in STANDBY below the 3 s threshold, but the RCU OFF→ON ticker forces fresh display frames every 1.5 s, so RCU liveness keeps the heartbeat honest. The Pi's local `config.yaml` had been tweaked to `tx_interval: 0.1` / `idle_interval: 0.4` as a workaround — that's still in effect but no longer load-bearing for this bug.
3. **Live °C/°F toggle** (`de5c99e`, `1c638bc`) — temperature unit is now configurable via `config.yaml` (`amp.temperature_unit: C|F`) and toggleable from the dashboard; the server writes the change back to YAML so it survives restart. The SPE protocol returns temperatures unit-less, so the server has to be told which unit the front panel is set to.
4. **README rewrite** (`af38e82`) — leads with the multi-client architecture diagram and the systemd install path.
5. **systemd installer** (`617c8b3`) — `install-service.sh` / `uninstall-service.sh` plus a sample Node-RED flow.
6. **Field rename** (`fd01936`) — JSON `model` → `model_id` to line up with the MacExpert decoder.
7. **Auto-detect amp model** (`9c0daaf`, `58c389a`) — scans the first 3 CSV fields of the status string for the model ID pattern and adapts the UI; robust against firmware variants.
8. **Python 3.9 compatibility** (`cd427c0`) — needed because Raspberry Pi OS Bookworm ships 3.9.
9. **Serial-stack fixes** (`3f69277`, `e1eec59`, `4f2bf2e`, `c3e48b9`) — the painful run: don't open a second pyserial handle for power control (was wedging the FTDI), restored `port.flush()` with write back-pressure, stopped saturating the amp's serial buffer by slowing the RCU tick and not speed-polling in OPER. Resolved the freeze that the diagnostic logging exposed.
10. **Reverted** (`d6fe518`, `94fe469`) — the FTDI settle / multi-port auto-discovery experiment was rolled back; the simple single-port approach won.

## Architecture invariants — don't break these

- **Only one process opens the serial port.** If you ever find yourself adding a second `serial.Serial(...)` call, stop. The power-control path was the trap that caused `3f69277`.
- **Threaded reader + async writer.** Blocking reads run on a thread because `serial_asyncio` was crashing on USB-serial poll glitches. Don't "modernize" this back to pure asyncio without testing on a real Pi + FTDI.
- **Mixed-client broadcast on the same WS.** Text JSON for browsers, binary RCU frames for MacExpert. Same socket, dispatched by message type.
- **Python 3.9 floor.** No `match` statements, no `X | Y` type unions in runtime code. Bookworm Pi is the deployment target.
- **No saturating the amp.** TX-poll interval and RCU tick rate were tuned by trial; bumping them up will wedge the amp's serial buffer again.

## Config (`config.yaml`)

- `serial.port` — uses the stable `/dev/serial/by-id/...` path, not `/dev/ttyUSB0`. Don't switch back; ttyUSB numbering changes across reboots.
- `polling.tx_interval` 0.2s, `idle_interval` 1.0s, `heartbeat` 15s — leave these alone unless you have a scope on the wire. The Pi runs locally-tweaked 0.1 / 0.4 values that are not in the default file.
- `polling.amp_alive_threshold` 3s — applies to the most recent of CSV state OR RCU display frame (see item 1 in Recent work). RCU OFF→ON ticks at 1.5s, so 3s is a generous margin while still flipping `serial:"down"` within ~3s of amp power-off (FTDI link survives, but no more RCU frames come back).
- `amp.temperature_unit` C or F — must match the SPE front-panel setting.
- `logging.level` INFO by default; DEBUG is loud (every serial write).

## Deployment

systemd unit `spe-remote.service` runs the server as a daemon. `install-service.sh` is the supported install path; the README tells users to clone the repo, run `setup.sh`, then `install-service.sh`. Service logs go to journald.

## Open threads / ideas (not started)

- No formal test suite. Everything has been tested against a live amp.
- Auth on the WebSocket — currently open on the LAN, fine for a shack network, would need a token for anything exposed.
- The dashboard's gauge rendering is canvas-based and hand-rolled; could move to a library but the current code is small and works on mobile.

## Where to pick up

Working tree is clean and pushed. Next session can start by reading this file and `git log --oneline -10` to confirm nothing landed in between. If a serial-stack bug reappears, re-read commits `3f69277`, `e1eec59`, `4f2bf2e` before changing anything — that whole sequence is the institutional memory for "don't touch the serial port lifecycle."
