"""Replay mode for judges without credentials (T-010, ADR-012).

Swaps only the two external systems, the PayPal client and the model client, for local
stand-ins driven by `data/replay.json`. Everything else in the app is the real code.
Enabled only by `python -m dispute_defender.web --replay`.
"""
from .data import DATA_PATH, ReplayData, ReplayDispute, load_replay

__all__ = ["DATA_PATH", "ReplayData", "ReplayDispute", "load_replay"]
