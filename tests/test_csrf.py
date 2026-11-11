"""Offline tests for the approval page's CSRF tokens (T-006, ADR-010)."""
from __future__ import annotations

import pytest

from dispute_defender.web.csrf import TTL_SECONDS, CsrfTokens

KEY = b"k" * 32
ID = "PP-R-HBV-10197617"


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def tokens(clock: Clock) -> CsrfTokens:
    return CsrfTokens(KEY, clock=clock)


def test_valid_token_is_accepted_once(tokens: CsrfTokens) -> None:
    token = tokens.issue(ID, "approve")
    assert tokens.consume(token, ID, "approve") is True
    assert tokens.consume(token, ID, "approve") is False


def test_tokens_are_unique(tokens: CsrfTokens) -> None:
    assert tokens.issue(ID, "draft") != tokens.issue(ID, "draft")


def test_wrong_dispute_is_refused(tokens: CsrfTokens) -> None:
    assert tokens.consume(tokens.issue(ID, "approve"), "PP-R-KXL-10197854", "approve") is False


def test_wrong_purpose_is_refused(tokens: CsrfTokens) -> None:
    assert tokens.consume(tokens.issue(ID, "draft"), ID, "approve") is False


def test_refused_attempt_does_not_burn_the_token(tokens: CsrfTokens) -> None:
    token = tokens.issue(ID, "approve")
    assert tokens.consume(token, ID, "draft") is False
    assert tokens.consume(token, ID, "approve") is True


def test_token_valid_until_ttl_then_expired(tokens: CsrfTokens, clock: Clock) -> None:
    first, second = tokens.issue(ID, "approve"), tokens.issue(ID, "approve")
    clock.now += TTL_SECONDS
    assert tokens.consume(first, ID, "approve") is True
    clock.now += 1
    assert tokens.consume(second, ID, "approve") is False


def test_token_from_the_future_is_refused(tokens: CsrfTokens, clock: Clock) -> None:
    clock.now += 3600
    token = tokens.issue(ID, "approve")
    clock.now -= 3600
    assert tokens.consume(token, ID, "approve") is False


def test_token_from_another_key_is_refused(clock: Clock) -> None:
    other = CsrfTokens(b"x" * 32, clock=clock).issue(ID, "approve")
    assert CsrfTokens(KEY, clock=clock).consume(other, ID, "approve") is False


def test_default_key_is_random_per_instance() -> None:
    token = CsrfTokens().issue(ID, "approve")
    assert CsrfTokens().consume(token, ID, "approve") is False


@pytest.mark.parametrize("part", [0, 1, 2])
def test_tampered_token_is_refused(tokens: CsrfTokens, part: int) -> None:
    pieces = tokens.issue(ID, "approve").split(".")
    piece = pieces[part]
    pieces[part] = piece[:-1] + ("0" if piece[-1] != "0" else "1")
    assert tokens.consume(".".join(pieces), ID, "approve") is False


@pytest.mark.parametrize(
    "token",
    ["", "abc", "1.2.3", "1.nonce-nonce-nonce." + "g" * 64, "x." * 3, None, 123, b"bytes", "é" * 90, "1" * 5000],
)
def test_malformed_token_is_refused(tokens: CsrfTokens, token: object) -> None:
    assert tokens.consume(token, ID, "approve") is False


def test_used_nonces_are_pruned_after_expiry(tokens: CsrfTokens, clock: Clock) -> None:
    for _ in range(5):
        assert tokens.consume(tokens.issue(ID, "draft"), ID, "draft")
    assert len(tokens._used) == 5
    clock.now += TTL_SECONDS + 1
    assert tokens.consume(tokens.issue(ID, "draft"), ID, "draft")
    assert len(tokens._used) == 1


def test_short_key_is_rejected() -> None:
    with pytest.raises(ValueError):
        CsrfTokens(b"short")
