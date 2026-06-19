"""Manual test driver for FlexConnection.

Phase 1 verification — run this on the Pi (or any host on the shack
LAN) to confirm spe-remote can talk to your Flex 6600. Defaults to
**read-only commands** so a fat-fingered typo can't key the radio:

    python3 -m spe.flex_cli                     # uses host/port from config.yaml
    python3 -m spe.flex_cli --host 192.168.1.148
    python3 -m spe.flex_cli --watch             # subscribes + tails events

Add ``--allow-tx`` and you get a prompt that accepts arbitrary commands
including the tune carrier. Use only with the SPE in STBY and an
antenna or dummy load known to be safe:

    python3 -m spe.flex_cli --allow-tx
    > slice s 0 mode=CWU
    > slice t 0 14.020
    > transmit set tunepower=10
    > transmit tune on
    > transmit tune off

Exit with Ctrl-D or `quit`.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from spe.config import load_config
from spe.flex import FlexConnection, FlexProtocolError


SAFE_PREFIXES = (
    "slice list",
    "slice get",
    "slice info",
    "radio info",
    "version",
    "info",
    "transmit info",
    "sub ",
)


def _is_safe(command: str) -> bool:
    cmd = command.strip().lower()
    return any(cmd.startswith(p) for p in SAFE_PREFIXES)


async def _interactive_loop(flex: FlexConnection, allow_tx: bool) -> None:
    print()
    print(f"Connected: version={flex.radio_version!r} handle={flex.client_handle!r}")
    print("Type a SmartSDR API command, e.g. `slice list`. Ctrl-D or `quit` to exit.")
    if not allow_tx:
        print("Read-only mode: TX-capable commands are blocked. Re-run with --allow-tx to enable.")
    print()
    loop = asyncio.get_event_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, sys.stdin.readline)
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        if line.lower() in ("quit", "exit"):
            break
        if not allow_tx and not _is_safe(line):
            print(f"  [blocked] {line!r} could key the radio — re-run with --allow-tx")
            continue
        try:
            msg = await flex.send(line)
        except FlexProtocolError as e:
            print(f"  ERROR: {e}")
            continue
        except asyncio.TimeoutError:
            print("  ERROR: no reply within timeout")
            continue
        print(f"  ok  msg={msg!r}" if msg else "  ok")


def _on_status(handle: str, message: str) -> None:
    print(f"  [event handle={handle}] {message}")


async def _main(args) -> int:
    if args.host:
        host = args.host
        port = args.port
    else:
        cfg = load_config(args.config)
        host = cfg.flex.host
        port = cfg.flex.port
        if not host:
            print(
                f"error: no Flex host configured.\n"
                f"  Either set flex.host in {args.config}, or pass --host on the CLI.",
                file=sys.stderr,
            )
            return 1

    flex = FlexConnection(host, port)
    flex.on_status = _on_status

    try:
        await flex.connect()
    except OSError as e:
        print(f"error: could not connect to {host}:{port}: {e}", file=sys.stderr)
        return 2

    try:
        # Sanity check: slice list. If this works we know the wire
        # protocol is correctly framed.
        try:
            reply = await flex.slice_list()
            print(f"slice list → {reply!r}")
        except FlexProtocolError as e:
            print(f"warning: slice list failed: {e}")

        if args.watch:
            # Subscribe and tail events until interrupted.
            try:
                await flex.subscribe("slice")
                await flex.subscribe("transmit")
                await flex.subscribe("radio")
            except FlexProtocolError as e:
                print(f"warning: subscribe failed: {e}")
            print("Watching events. Ctrl-C to quit.")
            try:
                await asyncio.Event().wait()
            except KeyboardInterrupt:
                pass
        else:
            await _interactive_loop(flex, args.allow_tx)
    finally:
        await flex.close()
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.yaml", help="Path to spe-remote config.yaml")
    ap.add_argument("--host", help="Override flex.host from config.yaml")
    ap.add_argument("--port", type=int, default=4992, help="Override flex.port (default 4992)")
    ap.add_argument("--watch", action="store_true",
                    help="Subscribe to slice/transmit/radio updates and tail them")
    ap.add_argument("--allow-tx", action="store_true",
                    help="Enable TX-capable commands (xmit, transmit tune, …)")
    args = ap.parse_args()
    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
