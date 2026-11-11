"""The offline UI preview script runs and its pages are self-contained (T-012)."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

from .conftest import FAKE_BUYER_VALUES, FAKE_TOKEN

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "preview_ui.py"
EXPECTED = {
    "index.html", "01-list.html", "02-dispute.html", "03-dispute-refused.html",
    "04-draft-dry.html", "05-result-dry.html", "04-draft-live.html", "05-result-live.html",
    "06-state.html", "07-message-refused.html", "08-error-paypal.html",
    "09-error-send-outcome-unknown.html", "10-error-invalid-input.html",
}
EXTERNAL = re.compile(r"https?://|//[a-z0-9.-]+\.[a-z]|@import|<script|<link|<img|src=|url\(", re.IGNORECASE)


@pytest.fixture(scope="module")
def preview() -> ModuleType:
    spec = importlib.util.spec_from_file_location("preview_ui", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pages(preview: ModuleType, tmp_path: Path) -> dict[str, str]:
    assert preview.main(["--out", str(tmp_path)]) == 0
    return {p.name: p.read_text() for p in tmp_path.iterdir()}


def test_every_page_is_written(pages: dict[str, str]) -> None:
    assert set(pages) == EXPECTED


def test_pages_have_no_external_resources_or_scripts(pages: dict[str, str]) -> None:
    for name, text in pages.items():
        assert not EXTERNAL.search(text), name


def test_both_banners_and_the_fake_csrf_token(pages: dict[str, str]) -> None:
    assert "DRY RUN: nothing will be sent" in pages["05-result-dry.html"]
    assert "LIVE SANDBOX SEND" in pages["05-result-live.html"]
    assert "LIVE SANDBOX SEND" in pages["04-draft-live.html"]
    assert 'name="csrf" value="FAKE-CSRF-TOKEN-preview-only"' in pages["02-dispute.html"]


def test_pages_show_what_they_are_named_for(pages: dict[str, str]) -> None:
    draft = pages["04-draft-dry.html"]
    for verdict in ("VERIFIED", "FLAGGED", "BLOCKED"):
        assert f'class="{verdict}"' in draft
    assert "Approve (dry run)" in draft
    assert "Dry run: nothing was sent" in pages["05-result-dry.html"]
    assert "Sent to the PayPal sandbox" in pages["05-result-live.html"]
    assert "Cannot respond now" in pages["03-dispute-refused.html"]
    assert "Read back from PayPal at 2026-11-10 18:30:05 UTC" in pages["06-state.html"]
    assert "HTTP 400" in pages["08-error-paypal.html"]
    assert "outcome of the send is unknown" in pages["09-error-send-outcome-unknown.html"]
    assert "Invalid input" in pages["10-error-invalid-input.html"]


def test_no_token_or_buyer_text_in_pages(pages: dict[str, str]) -> None:
    for name, text in pages.items():
        for secret in (FAKE_TOKEN, "FAKE-PREVIEW-SECRET", *FAKE_BUYER_VALUES):
            assert secret not in text, (name, secret)
