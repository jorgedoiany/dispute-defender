"""Run the approval page locally: `.venv/bin/python -m dispute_defender.web [--port N]`.

Binds to 127.0.0.1 only; there is no host option. Reads `.env` from the repo root
without overriding variables already set in the shell, so
`DISPUTE_DEFENDER_SEND_MODE=live` on the command line takes effect. Send mode is dry
unless that variable is `live`.

`--replay` (T-010, ADR-012) runs the app on local replay data instead: it reads no `.env`,
builds no PayPal or Bedrock client, ignores DISPUTE_DEFENDER_SEND_MODE and needs no
credentials. Only this flag turns replay on; no environment variable does.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv

from dispute_defender.drafter import BedrockModelClient, DrafterError, load_model_config
from dispute_defender.paypal import PayPalClient, PayPalError

from .app import create_app
from .settings import DEFAULT_PORT, HOST, load_send_mode

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("port must be a number") from None
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1024 and 65535")
    return port


def main(
    argv: Sequence[str] | None = None,
    *,
    env_file: Path = ENV_PATH,
    run: Callable[..., Any] = uvicorn.run,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m dispute_defender.web",
        description="Dispute Defender approval page on 127.0.0.1. PayPal sandbox only; dry run unless "
        "DISPUTE_DEFENDER_SEND_MODE=live.",
    )
    parser.add_argument("--port", type=_port, default=DEFAULT_PORT)
    parser.add_argument(
        "--replay", action="store_true",
        help="run on local replay data (simulated disputes, recorded model outputs); no credentials, "
        "no network, nothing is sent. Ignores .env and DISPUTE_DEFENDER_SEND_MODE.",
    )
    args = parser.parse_args(argv)

    if args.replay:
        return _run_replay(args.port, run)

    load_dotenv(env_file, override=False)
    try:
        paypal = PayPalClient.from_env()
        model_config = load_model_config()
        model_id = model_config.model("primary")
        model_client = BedrockModelClient.from_config(model_config)
    except (PayPalError, DrafterError) as exc:
        print(f"[web] cannot start | {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    send_mode = load_send_mode()
    app = create_app(paypal=paypal, model_client=model_client, model_id=model_id, send_mode=send_mode)
    label = "LIVE SANDBOX SEND" if send_mode == "live" else "DRY RUN (nothing is sent)"
    print(f"[web] http://{HOST}:{args.port} | send mode: {label} | model: {model_id}")
    run(app, host=HOST, port=args.port, server_header=False)
    return 0


def _run_replay(port: int, run: Callable[..., Any]) -> int:
    """Replay mode: no .env, no real clients, no credentials."""
    from dispute_defender.replay import ReplayModelClient, ReplayPayPalClient, load_replay, replay_model_label

    try:
        data = load_replay()
    except ValueError as exc:  # includes pydantic's ValidationError
        print(f"[web] cannot start replay | {type(exc).__name__}", file=sys.stderr)
        return 1
    if load_send_mode() == "live":
        print("[web] replay mode ignores DISPUTE_DEFENDER_SEND_MODE=live; nothing is sent", file=sys.stderr)
    model_id = replay_model_label(data)
    app = create_app(paypal=ReplayPayPalClient(data), model_client=ReplayModelClient(data),  # type: ignore[arg-type]
                     model_id=model_id, send_mode="replay")
    print(f"[web] http://{HOST}:{port} | mode: REPLAY (recorded and simulated data, nothing leaves this machine)"
          f" | model output: {model_id}")
    run(app, host=HOST, port=port, server_header=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
