"""`python -m dispute_defender.web --replay` (T-010, ADR-012). Offline.

Replay is enabled only by the flag: never by an environment variable or a `.env` line.
With the flag, no `.env` is read and no real PayPal or Bedrock client is built.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dispute_defender.web import __main__ as web_main

from .conftest import FAKE_CLIENT_ID, FAKE_SECRET

REPLAY_BANNER = "REPLAY: recorded and simulated data"
REPLAY_ENV_LINES = (
    "DISPUTE_DEFENDER_SEND_MODE=replay\nDISPUTE_DEFENDER_REPLAY=1\nREPLAY=1\nDISPUTE_DEFENDER_MODE=replay\n"
)


def _run(argv: list[str], env_file: Path) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake_run(app: Any, **kwargs: Any) -> None:
        seen["app"] = app
        seen.update(kwargs)

    seen["code"] = web_main.main(argv, env_file=env_file, run=fake_run)
    return seen


@pytest.fixture
def isolated_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """load_dotenv writes to os.environ; give it a throwaway copy."""
    monkeypatch.setattr(os, "environ", os.environ.copy())


def _forbid_real_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("replay mode must not read .env or build real clients")

    monkeypatch.setattr(web_main, "load_dotenv", forbidden)
    monkeypatch.setattr(web_main.PayPalClient, "from_env", forbidden)
    monkeypatch.setattr(web_main, "load_model_config", forbidden)
    monkeypatch.setattr(web_main.BedrockModelClient, "from_config", forbidden)


def test_replay_flag_builds_only_replay_clients(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    _forbid_real_setup(monkeypatch)
    monkeypatch.delenv("DISPUTE_DEFENDER_SEND_MODE", raising=False)
    seen = _run(["--replay", "--port", "8124"], tmp_path / "no.env")
    assert seen["code"] == 0
    assert seen["host"] == "127.0.0.1" and seen["port"] == 8124
    out = capsys.readouterr().out
    assert "REPLAY" in out and "nothing leaves this machine" in out
    page = TestClient(seen["app"], base_url="http://127.0.0.1").get("/")
    assert page.status_code == 200 and REPLAY_BANNER in page.text


def test_replay_flag_ignores_live_send_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    _forbid_real_setup(monkeypatch)
    monkeypatch.setenv("DISPUTE_DEFENDER_SEND_MODE", "live")
    seen = _run(["--replay"], tmp_path / "no.env")
    assert seen["code"] == 0
    assert "ignores DISPUTE_DEFENDER_SEND_MODE=live" in capsys.readouterr().err
    page = TestClient(seen["app"], base_url="http://127.0.0.1").get("/").text
    assert REPLAY_BANNER in page and "LIVE SANDBOX SEND" not in page


def test_env_and_dotenv_cannot_enable_replay(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                             isolated_environ: None) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"PAYPAL_CLIENT_ID={FAKE_CLIENT_ID}\nPAYPAL_CLIENT_SECRET={FAKE_SECRET}\n"
        "AWS_REGION=us-east-1\nBEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6\n" + REPLAY_ENV_LINES
    )
    for line in REPLAY_ENV_LINES.split():  # in the shell too
        name, value = line.split("=", 1)
        os.environ[name] = value
    seen = _run([], env_file)
    assert seen["code"] == 0
    assert os.environ["PAYPAL_CLIENT_ID"] == FAKE_CLIENT_ID  # the .env file was read
    page = TestClient(seen["app"], base_url="http://127.0.0.1").post(
        "/disputes/PP-R-SIM-N1/draft", data={})  # 403 page, rendered without any PayPal call
    assert "DRY RUN: nothing will be sent" in page.text and "REPLAY" not in page.text


def test_replay_mode_cannot_be_selected_from_the_environment() -> None:
    from dispute_defender.web import load_send_mode

    for value in ("replay", "REPLAY", " replay ", "live-replay"):
        assert load_send_mode({"DISPUTE_DEFENDER_SEND_MODE": value}) == "dry"


def test_replay_flag_reports_bad_data_safely(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    import dispute_defender.replay as replay_pkg

    def broken() -> Any:
        raise ValueError("replay data must be labelled")

    _forbid_real_setup(monkeypatch)
    monkeypatch.setattr(replay_pkg, "load_replay", broken)
    seen = _run(["--replay"], tmp_path / "no.env")
    assert seen["code"] == 1 and "app" not in seen
    assert "cannot start replay" in capsys.readouterr().err
