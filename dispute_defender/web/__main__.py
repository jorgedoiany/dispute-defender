"""Run the approval page locally: `.venv/bin/python -m dispute_defender.web [--port N]`.

Binds to 127.0.0.1 only; there is no host option. Reads `.env` from the repo root
without overriding variables already set in the shell, so
`DISPUTE_DEFENDER_SEND_MODE=live` on the command line takes effect. Send mode is dry
unless that variable is `live`.
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
    args = parser.parse_args(argv)

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


if __name__ == "__main__":
    sys.exit(main())
