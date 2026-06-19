"""One-shot Flex tune-carrier test.

Connects, sets slice 0 to a safe freq, emits a 10 W carrier for 3
seconds, then unkeys. No interactive prompt — sidesteps the readline
buffering issues seen during the manual interlock-dance test
2026-06-19. Run it, watch the SPE display, see whether the bypass-OP
screen comes up with a live drive reading.

Usage:
    cd ~/spe-remote
    python3 -m spe.flex_carrier_test            # 14.020 MHz, 10 W, 3 s
    python3 -m spe.flex_carrier_test --freq 7.020 --power 5 --hold 5

Preflight checklist:
    * SPE in STBY (the script does NOT touch the amp).
    * Antenna or dummy load connected on whichever port carries
      slice 0's TX antenna (check `slice list` first if unsure).
    * SmartSDR Console can be open or closed — doesn't matter,
      tune carrier works either way.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from spe.config import load_config
from spe.flex import FlexConnection, FlexProtocolError


async def _run(host: str, port: int, freq_mhz: float, power_w: int,
               hold_s: float) -> int:
    flex = FlexConnection(host, port)
    try:
        await flex.connect()
    except OSError as e:
        print(f"error: could not connect to {host}:{port}: {e}", file=sys.stderr)
        return 2

    try:
        print(f"Connected: version={flex.radio_version!r}")
        print(f"Step 1/5: set slice 0 → {freq_mhz} MHz")
        try:
            await flex.set_slice_freq(0, freq_mhz)
        except FlexProtocolError as e:
            print(f"  FAILED: {e}", file=sys.stderr)
            return 3

        print(f"Step 2/5: set tune power → {power_w} W")
        try:
            await flex.set_tune_power(power_w)
        except FlexProtocolError as e:
            print(f"  FAILED: {e}", file=sys.stderr)
            return 3

        print(f"Step 3/5: carrier ON in 2 s — watch the SPE display.")
        await asyncio.sleep(2)
        try:
            await flex.tune_carrier(on=True)
        except FlexProtocolError as e:
            print(f"  FAILED: {e}", file=sys.stderr)
            return 3
        print(f"Step 4/5: CARRIER ON — holding {hold_s} s. "
              f"SPE should show bypass-OP screen with ~{power_w} W drive.")

        try:
            await asyncio.sleep(hold_s)
        finally:
            # Always unkey, even on Ctrl-C, KeyboardInterrupt, etc.
            print("Step 5/5: carrier OFF")
            try:
                await flex.tune_carrier(on=False)
            except FlexProtocolError as e:
                print(f"  FAILED to unkey: {e}", file=sys.stderr)
                return 4

        print("Done. Did the SPE switch to bypass-OP with a live drive reading?")
        return 0
    finally:
        await flex.close()


def main() -> None:
    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.yaml", help="spe-remote config")
    ap.add_argument("--host", help="Override flex.host from config.yaml")
    ap.add_argument("--port", type=int, default=4992,
                    help="Override flex.port (default 4992)")
    ap.add_argument("--freq", type=float, default=14.020,
                    help="MHz to tune slice 0 to (default 14.020)")
    ap.add_argument("--power", type=int, default=10,
                    help="Tune power in watts (default 10, max 100)")
    ap.add_argument("--hold", type=float, default=3.0,
                    help="Seconds to hold the carrier (default 3)")
    args = ap.parse_args()

    if args.host:
        host, port = args.host, args.port
    else:
        cfg = load_config(args.config)
        host = cfg.flex.host
        port = cfg.flex.port
        if not host:
            print("error: flex.host not set in config.yaml and --host not given",
                  file=sys.stderr)
            sys.exit(1)

    sys.exit(asyncio.run(_run(host, port, args.freq, args.power, args.hold)))


if __name__ == "__main__":
    main()
